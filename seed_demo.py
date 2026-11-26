"""
Build the demo registry from the public Zenodo muzzle dataset.

    python seed_demo.py path/to/BeefCattle_Muzzle_Individualized

Creates:
  demo_db/        20 registered cows with sample Indian owner details (fictional)
  demo_photos/    unseen photos to try in the Identify tab:
                    registered/   new photos of registered cows   -> should match
                    unregistered/ cows that were never registered -> "Not registered"
                    duplicate/    cow 4454 = same animal as registered cow 4451 in
                                  the dataset (labelling error)   -> "Already registered"

Dataset: "Beef Cattle Muzzle/Noseprint database", Zenodo record 6324361, CC-BY 4.0.
"""

import os
import random
import shutil
import sys

import cv2

import pashu_core as pc

HERE = os.path.dirname(os.path.abspath(__file__))
N_COWS = 20

OWNERS = ["Ramesh Patel", "Sunita Devi", "Harpal Singh", "Lakshmi Bai", "Mohan Yadav",
          "Geeta Chaudhary", "Babulal Meena", "Kavita Rathore", "Suresh Gowda", "Anita Kumari",
          "Bhola Prasad", "Rekha Jat", "Govind Ahir", "Shanti Bhil", "Dinesh Rabari",
          "Pushpa Thakur", "Rajendra Gurjar", "Meera Solanki", "Vikram Choudhary", "Sarita Mali"]
VILLAGES = ["Anand, Gujarat", "Bikaner, Rajasthan", "Ludhiana, Punjab", "Karnal, Haryana",
            "Mathura, UP", "Junagadh, Gujarat", "Hisar, Haryana", "Mandya, Karnataka",
            "Nagaur, Rajasthan", "Sitapur, UP"]
BREEDS = ["Gir", "Sahiwal", "Tharparkar", "Rathi", "Kankrej", "Hallikar", "HF cross",
          "Jersey cross", "Red Sindhi", "Hariana"]
INSURANCE = ["Insured", "Insured", "Not insured", "Claim pending"]


def small(path, max_side=900):
    img = pc.load_image(path)
    s = max_side / max(img.shape[:2])
    return cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img


def photos(root, cow):
    d = os.path.join(root, cow)
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith((".jpg", ".png")))


def main(root):
    random.seed(2026)
    for d in ("demo_db", "demo_photos"):
        shutil.rmtree(os.path.join(HERE, d), ignore_errors=True)
    reg = pc.Registry(os.path.join(HERE, "demo_db"))
    out = os.path.join(HERE, "demo_photos")
    for sub in ("registered", "unregistered", "duplicate"):
        os.makedirs(os.path.join(out, sub))

    skip = {"cattle_4451", "cattle_4454", "cattle_5407", "cattle_6011"}  # mislabelled pairs
    cows = sorted(c for c in os.listdir(root) if c not in skip and len(photos(root, c)) >= 6)
    random.shuffle(cows)
    candidates = ["cattle_4451"] + cows
    k = 0
    while k < N_COWS:
        cow = candidates.pop(0)
        ps = photos(root, cow)
        random.shuffle(ps)
        info = dict(owner=OWNERS[k], phone="", village=VILLAGES[k % len(VILLAGES)],
                    species="Cow · गाय", breed=BREEDS[k % len(BREEDS)], tag="",
                    insurance=INSURANCE[k % len(INSURANCE)], source=cow)
        enrolled, used = [], 0
        for p in ps:                       # first 3 photos that pass the quality check
            if len(enrolled) == 3:
                break
            used += 1
            img = small(p)
            if not pc.check_quality(img, len(pc.extract(img)[1])):
                enrolled.append(img)
        if len(enrolled) < 3:
            continue                       # not enough sharp photos of this cow
        cid, _ = reg.enroll(enrolled, info)
        for j, p in enumerate(ps[used:used + 2]):   # unseen photos for the demo
            cv2.imwrite(os.path.join(out, "registered", f"{cid}_{OWNERS[k].split()[0]}_{j + 1}.jpg"),
                        small(p, 800))
        print(f"{cid}  {OWNERS[k]:<18} {cow}")
        k += 1
    unregistered = candidates[:5]

    for cow in unregistered:
        cv2.imwrite(os.path.join(out, "unregistered", f"unknown_{cow}.jpg"), small(photos(root, cow)[0], 800))
    for j, p in enumerate(photos(root, "cattle_4454")[-3:]):
        cv2.imwrite(os.path.join(out, "duplicate", f"same_as_Ramesh_{j + 1}.jpg"), small(p, 800))
    print(f"\nDemo registry: {len(reg)} cows in demo_db/, test photos in demo_photos/")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
