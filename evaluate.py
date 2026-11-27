import argparse
import os
import random
import time

import numpy as np

import pashu_core as pc

EXT = (".jpg", ".jpeg", ".png", ".bmp")


def main():
    ap = argparse.ArgumentParser(description="Measure Pashu Aadhaar accuracy on a muzzle dataset.")
    ap.add_argument("root")
    ap.add_argument("--cows", type=int, default=50, help="cows to register (more = slower)")
    ap.add_argument("--unknown", type=int, default=20, help="extra cows kept unregistered")
    ap.add_argument("--enroll", type=int, default=3, help="photos per cow to register")
    ap.add_argument("--queries", type=int, default=3, help="test photos per cow")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--show-errors", action="store_true",
                    help="list wrong matches above the threshold")
    ap.add_argument("--no-quality", dest="quality", action="store_false",
                    help="don't apply the app's photo quality check")
    a = ap.parse_args()

    random.seed(a.seed)
    folders = []
    for d in sorted(os.listdir(a.root)):
        p = os.path.join(a.root, d)
        if os.path.isdir(p):
            imgs = sorted(f for f in os.listdir(p) if f.lower().endswith(EXT))
            if len(imgs) >= a.enroll + 1:
                folders.append((d, [os.path.join(p, f) for f in imgs]))
    random.shuffle(folders)
    known = folders[:a.cows]
    unknown = folders[a.cows:a.cows + a.unknown]
    print(f"Found {len(folders)} usable cows. Registering {len(known)}, "
          f"keeping {len(unknown)} as unknown.")

    t0 = time.time()
    gallery = pc.GalleryIndex()
    tests = []
    for cow, imgs in known:
        random.shuffle(imgs)
        for i, p in enumerate(imgs[:a.enroll]):
            img = pc.load_image(p)
            pts, des, _ = pc.extract(img)
            if a.quality and pc.check_quality(img, len(des)):
                continue
            gallery.add(cow, i, (pts, des))
        tests += [(cow, p) for p in imgs[a.enroll:a.enroll + a.queries]]
    for cow, imgs in unknown:
        tests += [(None, p) for p in imgs[:2]]
    print(f"Enrolled {len(gallery.items)} photos in {time.time() - t0:.1f}s. "
          f"Running {len(tests)} queries...")

    genuine, impostor = [], []
    rows = []
    t0 = time.time()
    retakes = 0
    for k, (truth, p) in enumerate(tests, 1):
        img = pc.load_image(p)
        q = pc.extract(img)[:2]
        if a.quality and pc.check_quality(img, len(q[1])):
            retakes += 1
            continue
        best = {label: s for s, label, _ in gallery.search(q)}
        ranked = sorted(best.items(), key=lambda x: -x[1]) or [(None, 0)]
        top_cow, top_s = ranked[0]
        if truth is not None:
            genuine.append(best.get(truth, 0))
            wrong = max([s for c, s in best.items() if c != truth] or [0])
        else:
            wrong = top_s
        impostor.append(wrong)
        rows.append((truth, top_cow, top_s))
        if a.show_errors and top_cow != truth and top_s >= pc.DEFAULT_THRESHOLD:
            print(f"  WRONG: {os.path.basename(p)} (truth {truth or 'unregistered'}) "
                  f"-> {top_cow} with {top_s} ridge points")
        if k % 20 == 0:
            print(f"  {k}/{len(tests)}")
    dt = (time.time() - t0) / max(len(tests), 1)

    genuine, impostor = np.array(genuine), np.array(impostor)
    print("\n=== Score distribution (inliers) ===")
    print(f"Same cow:      median {np.median(genuine):.0f}, 10th pct {np.percentile(genuine, 10):.0f}")
    print(f"Different cow: median {np.median(impostor):.0f}, 99th pct {np.percentile(impostor, 99):.0f}, "
          f"max {impostor.max():.0f}")

    print("\n=== Accuracy at different thresholds ===")
    print("thresh | correct ID (known cows) | wrongly accepted (unknown cows) | false ID")
    best_t, best_f = None, -1
    for t in sorted({8, 10, 12, 15, 18, 20, 25, 30, 40, pc.DEFAULT_THRESHOLD}):
        k_tot = k_ok = u_tot = u_fa = wrong_id = 0
        for truth, top, s in rows:
            if truth is None:
                u_tot += 1
                u_fa += s >= t
            else:
                k_tot += 1
                if s >= t:
                    if top == truth:
                        k_ok += 1
                    else:
                        wrong_id += 1
        tpr = k_ok / max(k_tot, 1)
        far = u_fa / max(u_tot, 1)
        print(f"{t:6d} | {100 * tpr:22.1f}% | {100 * far:30.1f}% | {wrong_id}")
        score = tpr - 2 * far - 0.02 * wrong_id
        if score > best_f:
            best_f, best_t = score, t
    rank1 = np.mean([top == truth for truth, top, _ in rows if truth is not None])
    print(f"\nRank-1 identification accuracy (no threshold): {100 * rank1:.1f}% "
          f"across {len(known)} cows")
    print(f"Suggested threshold: {best_t}  (set DEFAULT_THRESHOLD in pashu_core.py)")
    print(f"Average time per search: {dt * 1000:.0f} ms against {len(gallery.items)} photos")
    if a.quality:
        print(f"Photos the app would ask to retake (blur/dark/too far): "
              f"{retakes}/{len(tests)} ({100 * retakes / max(len(tests), 1):.1f}%)")


if __name__ == "__main__":
    main()
