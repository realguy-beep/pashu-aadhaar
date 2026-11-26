"""
Pashu Aadhaar - core muzzle (nose-print) matching engine.

How it works (simple version for the pitch):
  1. Clean the photo: grayscale, fixed size, boost contrast (CLAHE) so the
     ridges and beads of the nose print stand out.
  2. Find hundreds of tiny "landmarks" in the ridge pattern (SIFT keypoints).
  3. To compare two noses, match landmarks and keep only the ones that agree
     on one consistent geometric transform (RANSAC). The number of agreeing
     landmarks ("inliers") is the match score.
  4. Same cow -> many inliers. Different cow -> very few.

No training needed, so a new cow can be registered from 2-3 photos instantly.
"""

import json
import os
import shutil
import threading
import time
import uuid

import cv2
import numpy as np

IMG_SIZE = 300          # all muzzle crops are resized to this
MAX_FEATURES = 1200     # keypoints per image
RATIO = 0.75            # Lowe's ratio test
DEFAULT_THRESHOLD = 15  # min inliers to accept a match (tuned with evaluate.py on Zenodo dataset)

_sift = cv2.SIFT_create(nfeatures=MAX_FEATURES)
_clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
_flann = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=50))


# ---------------------------------------------------------------- features
def load_image(path_or_bytes):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        arr = np.frombuffer(path_or_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    else:
        img = cv2.imread(str(path_or_bytes), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not read image")
    return img


def preprocess(img):
    """Square centre-crop -> resize -> grayscale -> contrast boost."""
    h, w = img.shape[:2]
    s = min(h, w)
    y0, x0 = (h - s) // 2, (w - s) // 2
    img = img[y0:y0 + s, x0:x0 + s]
    img = cv2.resize(img, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gray = _clahe.apply(gray)
    return gray


def extract(img):
    """Returns (keypoint array Nx2, descriptors Nx128 float32, processed gray)."""
    gray = preprocess(img)
    kps, des = _sift.detectAndCompute(gray, None)
    if des is None or len(kps) < 5:
        return np.zeros((0, 2), np.float32), np.zeros((0, 128), np.float32), gray
    pts = np.array([k.pt for k in kps], np.float32)
    return pts, des.astype(np.float32), gray


def match(feat_a, feat_b, return_pairs=False):
    """Score two feature sets. Returns number of geometric inliers."""
    pa, da = feat_a
    pb, db = feat_b
    if len(da) < 5 or len(db) < 5:
        return (0, []) if return_pairs else 0
    knn = _flann.knnMatch(da, db, k=2)
    good = []
    for pair in knn:
        if len(pair) == 2 and pair[0].distance < RATIO * pair[1].distance:
            good.append(pair[0])
    if len(good) < 6:
        return (0, []) if return_pairs else 0
    src = pa[[m.queryIdx for m in good]]
    dst = pb[[m.trainIdx for m in good]]
    # Partial affine (rotation + scale + shift): robust for nose photos
    _, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                          ransacReprojThreshold=6.0,
                                          maxIters=2000, confidence=0.99)
    if mask is None:
        return (0, []) if return_pairs else 0
    mask = mask.ravel().astype(bool)
    inliers = int(mask.sum())
    if return_pairs:
        pairs = [(tuple(src[i]), tuple(dst[i])) for i in np.where(mask)[0]]
        return inliers, pairs
    return inliers


def draw_match(gray_a, gray_b, pairs, max_lines=60):
    """Side-by-side picture with green lines between matching ridge points."""
    a = cv2.cvtColor(gray_a, cv2.COLOR_GRAY2BGR)
    b = cv2.cvtColor(gray_b, cv2.COLOR_GRAY2BGR)
    gap = np.full((IMG_SIZE, 12, 3), 255, np.uint8)
    canvas = np.hstack([a, gap, b])
    off = IMG_SIZE + 12
    rng = np.random.default_rng(0)
    sel = pairs if len(pairs) <= max_lines else [pairs[i] for i in
                                                 rng.choice(len(pairs), max_lines, replace=False)]
    for (x1, y1), (x2, y2) in sel:
        p1 = (int(x1), int(y1))
        p2 = (int(x2) + off, int(y2))
        cv2.line(canvas, p1, p2, (60, 200, 60), 1, cv2.LINE_AA)
        cv2.circle(canvas, p1, 3, (0, 140, 255), -1)
        cv2.circle(canvas, p2, 3, (0, 140, 255), -1)
    return canvas


def confidence(inliers, threshold=DEFAULT_THRESHOLD):
    """Map inlier count to a friendly 0-100% number for the UI."""
    x = (inliers - threshold) / max(threshold, 1)
    return float(round(100 / (1 + np.exp(-3 * x)), 1))


# ---------------------------------------------------------------- fast search
class GalleryIndex:
    """Two-stage search so it stays fast with thousands of cows.

    Stage 1 (voting): every registered photo's features go into ONE index.
      Each feature of the query photo votes for the cow it most resembles
      (only if it clearly beats the best feature from any *other* cow).
    Stage 2 (verification): only the top few candidate photos get the full
      geometric check (RANSAC inliers), which gives the final score.
    """

    def __init__(self, shortlist=8):
        self.shortlist = shortlist
        self.items = []      # (label, image_index, (pts, des))
        self._index = None

    def add(self, label, img_i, feat):
        if len(feat[1]) >= 5:
            self.items.append((label, img_i, feat))
            self._index = None

    def _build(self):
        des = [f[1] for _, _, f in self.items]
        self._owner = np.concatenate([np.full(len(d), k, np.int32)
                                      for k, d in enumerate(des)])
        self._labels = [l for l, _, _ in self.items]
        self._index = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=64))
        self._index.add([np.concatenate(des)])
        self._index.train()

    def search(self, q):
        """q = (pts, des). Returns list of (inliers, label, image_index), best first."""
        if not self.items or len(q[1]) < 5:
            return []
        if self._index is None:
            self._build()
        knn = self._index.knnMatch(q[1], k=6)
        votes = np.zeros(len(self.items))
        for nbrs in knn:
            if not nbrs:
                continue
            first = nbrs[0]
            own = self._owner[first.trainIdx]
            lab = self._labels[own]
            # nearest neighbour belonging to a different cow
            other = next((n for n in nbrs[1:]
                          if self._labels[self._owner[n.trainIdx]] != lab), None)
            if other is None or first.distance < RATIO * other.distance:
                votes[own] += 1
        cand = np.argsort(-votes)[:self.shortlist]
        out = []
        for k in cand:
            if votes[k] == 0:
                break
            label, img_i, feat = self.items[k]
            out.append((match(q, feat), label, img_i))
        # best image per cow
        best = {}
        for s, label, img_i in out:
            if label not in best or s > best[label][0]:
                best[label] = (s, label, img_i)
        return sorted(best.values(), key=lambda x: -x[0])


# ---------------------------------------------------------------- quality
MIN_KEYPOINTS = 40      # fewer ridge features than this = unusable photo
MIN_SHARPNESS = 8.0     # variance of Laplacian on the 300px crop (tuned on Zenodo dataset)
MIN_BRIGHT, MAX_BRIGHT = 35, 225


def check_quality(img, n_keypoints):
    """Returns a short, user-facing problem string, or None if the photo is OK."""
    h, w = img.shape[:2]
    s = min(h, w)
    g = img[(h - s) // 2:(h - s) // 2 + s, (w - s) // 2:(w - s) // 2 + s]
    g = cv2.resize(g, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
    g = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY) if g.ndim == 3 else g
    bright = float(g.mean())
    if bright < MIN_BRIGHT:
        return "too dark, take it in daylight / बहुत अंधेरा"
    if bright > MAX_BRIGHT:
        return "too bright / glare, avoid direct flash / बहुत चमक"
    if cv2.Laplacian(g, cv2.CV_64F).var() < MIN_SHARPNESS:
        return "blurry, hold steady and retake / धुंधली फोटो"
    if n_keypoints < MIN_KEYPOINTS:
        return "nose pattern not visible, move closer so the nose fills the box / नाक पास से लें"
    return None


class DuplicateError(Exception):
    def __init__(self, cid, inliers, info):
        super().__init__(f"Already registered as {cid}")
        self.cid, self.inliers, self.info = cid, inliers, info


# ---------------------------------------------------------------- registry
class Registry:
    """Stores registered cows on disk: db/<cow_id>/{info.json, *.jpg, feats.npz}"""

    def __init__(self, root="db"):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self._lock = threading.RLock()
        self._cache = {}
        self.reload()

    def _rebuild_index(self):
        self._gi = GalleryIndex()
        for cid, v in self._cache.items():
            for i, f in enumerate(v["feats"]):
                self._gi.add(cid, i, f)

    def reload(self):
        self._cache = {}
        self._gi = GalleryIndex()
        for cid in sorted(os.listdir(self.root)):
            d = os.path.join(self.root, cid)
            fp = os.path.join(d, "feats.npz")
            if not os.path.isfile(fp):
                continue
            z = np.load(fp, allow_pickle=False)
            feats = [(z[f"p{i}"], z[f"d{i}"]) for i in range(int(z["n"]))]
            with open(os.path.join(d, "info.json"), encoding="utf-8") as f:
                info = json.load(f)
            self._cache[cid] = {"info": info, "feats": feats}
        self._rebuild_index()

    def __len__(self):
        return len(self._cache)

    def cows(self):
        """Newest first."""
        out = [dict(id=c, **v["info"]) for c, v in self._cache.items()]
        return sorted(out, key=lambda c: c.get("registered_at", ""), reverse=True)

    def has(self, cid):
        return cid in self._cache

    def info(self, cid):
        return self._cache[cid]["info"]

    def photo_path(self, cid, i=0):
        return os.path.join(self.root, cid, f"photo_{i}.jpg")

    def delete(self, cid):
        with self._lock:
            if cid not in self._cache:
                return False
            shutil.rmtree(os.path.join(self.root, cid), ignore_errors=True)
            del self._cache[cid]
            self._rebuild_index()
            return True

    def _duplicate_of(self, feats, threshold):
        """(cow_id, inliers) if any of these feature sets matches a registered cow."""
        best = None
        for f in feats:
            scores = self._gi.search(f)
            if scores and scores[0][0] >= threshold and (best is None or scores[0][0] > best[1]):
                best = (scores[0][1], scores[0][0])
        return best

    def enroll(self, images, info, threshold=DEFAULT_THRESHOLD):
        """images: list of BGR arrays (2-3 recommended). info: dict of details.
        Returns (cow_id, list of rejected-photo messages).
        Raises DuplicateError if this cow is already registered, ValueError if
        no photo is usable."""
        good, rejected = [], []
        for k, img in enumerate(images, 1):
            pts, des, gray = extract(img)
            problem = check_quality(img, len(des))
            if problem:
                rejected.append(f"Photo {k}: {problem}")
            else:
                good.append((img, pts, des, gray))
        if not good:
            raise ValueError("No usable nose photo. " + " ".join(rejected))
        with self._lock:
            dup = self._duplicate_of([(p, d) for _, p, d, _ in good], threshold)
            if dup:
                raise DuplicateError(dup[0], dup[1], self._cache[dup[0]]["info"])
            cid = info.get("id") or "PA-" + uuid.uuid4().hex[:8].upper()
            d = os.path.join(self.root, cid)
            os.makedirs(d, exist_ok=True)
            arrays = {}
            for n, (img, pts, des, gray) in enumerate(good):
                cv2.imwrite(os.path.join(d, f"photo_{n}.jpg"), gray)
                cv2.imwrite(os.path.join(d, f"original_{n}.jpg"), img)  # keep for future models
                arrays[f"p{n}"], arrays[f"d{n}"] = pts, des
            n = len(good)
            np.savez_compressed(os.path.join(d, "feats.npz"), n=n, **arrays)
            info = {k: v for k, v in info.items() if k != "id"}
            info.update(registered_at=time.strftime("%Y-%m-%d %H:%M"), photos=n)
            with open(os.path.join(d, "info.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)
            self._cache[cid] = {"info": info,
                                "feats": [(arrays[f"p{i}"], arrays[f"d{i}"]) for i in range(n)]}
            self._rebuild_index()
        return cid, rejected

    def identify(self, img, threshold=DEFAULT_THRESHOLD, top_k=3):
        """Returns dict with best match (or None) and a ranked candidate list.
        Raises ValueError if the photo is too poor to search with."""
        q = extract(img)
        problem = check_quality(img, len(q[1]))
        if problem:
            raise ValueError(problem)
        with self._lock:
            return self._identify(q, threshold, top_k)

    def _identify(self, q, threshold, top_k):
        scores = self._gi.search(q[:2])
        ranked = [{"id": c, "inliers": s, "confidence": confidence(s, threshold),
                   **self._cache[c]["info"]} for s, c, _ in scores[:top_k]]
        result = {"query_keypoints": len(q[1]), "candidates": ranked, "match": None, "visual": None}
        if scores and scores[0][0] >= threshold:
            s, cid, i = scores[0]
            result["match"] = ranked[0]
            _, pairs = match(q[:2], self._cache[cid]["feats"][i], return_pairs=True)
            ref = cv2.imread(self.photo_path(cid, i), cv2.IMREAD_GRAYSCALE)
            result["visual"] = draw_match(q[2], ref, pairs)
        return result
