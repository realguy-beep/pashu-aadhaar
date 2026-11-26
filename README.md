# 🐄 Pashu Aadhaar — nose-print ID for cattle

Every cow's muzzle (nose) has a unique pattern of ridges and beads, like a human
fingerprint. Pashu Aadhaar registers a cow from 2–3 phone photos of its nose and
later identifies it from a single new photo. No ear tag needed, and no AI training
needed to add a new cow.

## Files

| File | What it does |
|---|---|
| `pashu_core.py` | The matching engine (photo cleanup, ridge feature detection, matching, fast search) |
| `app.py` | Demo web app: Register a cow, Identify a cow, view the Registry (English + Hindi labels) |
| `evaluate.py` | Measures accuracy on a dataset. **This gives you the numbers for your application.** |
| `seed_demo.py` | Builds the demo registry (`demo_db/`, 20 cows) and test photos (`demo_photos/`) from the public dataset |
| `demo_photos/` | Photos to try: `registered/` (should match), `unregistered/` (should be rejected), `duplicate/` (try registering it, gets blocked), `retake/` (blurry) |
| `render.yaml` | One-click deploy config for Render.com |

## Try the demo

A fresh install loads 20 demo cows automatically (owners and villages are fictional; nose
photos are from the public dataset below). Then:

- **Identify** → upload `demo_photos/registered/PA-5C738588_Ramesh_1.jpg` → ✅ Ramesh Patel's cow
- **Identify** → any photo in `demo_photos/unregistered/` → ❌ Not registered
- **Register** → `demo_photos/duplicate/same_as_Ramesh_1.jpg` → 🚫 duplicate blocked
- **Identify** → `demo_photos/retake/blurry_1.jpg` → asks for a retake

## Deploy (free, on Render)

1. Push this folder to GitHub.
2. On https://render.com: **New → Blueprint**, pick the repo. Render reads `render.yaml`.
3. Wait about 5 minutes for the build. You get a `https://…onrender.com` link that works on any phone.

Notes: the free plan sleeps after 15 min idle, so the first visit takes about 1 minute (open it before a
demo). Its disk resets on redeploy or restart, so the registry goes back to the 20 demo cows.

## Credits

Nose photos: *Beef Cattle Muzzle/Noseprint database for individual identification*,
Zenodo record [6324361](https://zenodo.org/record/6324361), licensed CC-BY 4.0.

## 1. Setup (5 minutes)

Install Python 3.9+ first, then in this folder run:

```
pip install -r requirements.txt
python app.py
```

Open **http://localhost:5000**. To use a phone camera, connect the phone to the same
Wi-Fi and open `http://<laptop-IP>:5000` (on Windows, find the IP with `ipconfig`).

## 2. Get real cow nose photos

**Public dataset (free, CC-BY 4.0):** "Beef Cattle Muzzle/Noseprint database",
4,923 photos of 268 cows → https://zenodo.org/record/6324361
Download `BeefCattle_Muzzle_database.zip` and unzip it. It has one folder per cow.

**Your own Indian cows (do this, it makes the pitch 10× stronger):** visit a local
dairy or gaushala and photograph 5–10 cows. Take 4–5 close-up nose photos per cow,
a few seconds apart. Crop each photo so the nose fills the frame. Note the owner
name and breed. Ask the owner's permission first.

## 3. Measure accuracy (your headline number)

```
python evaluate.py path/to/BeefCattle_Muzzle_database --cows 100 --unknown 30
```

It prints:
- **Rank-1 accuracy**: how often the right cow is top of the list
- **Correct ID / wrongly accepted** at different thresholds: pick the threshold where
  "wrongly accepted" is ~0–2% while "correct ID" stays high
- **Search time** per photo

Then set `DEFAULT_THRESHOLD` in `pashu_core.py` to the suggested value.
Screenshot this output for the application. If accuracy is low, see the tips below.

> **Results on the real Zenodo dataset** (100 registered cows, 168 unregistered, 632 test photos,
> threshold 15): rank-1 accuracy 97.4%, correct ID 96.7%, 128 ms per search. All 4 "wrong"
> matches turned out to be the same cow filed under two IDs in the dataset itself
> (4451/4454, 5407/6011), so there were no genuine false matches. Use `--show-errors` to list them.

## 4. Demo video plan (about 2 minutes)

1. **Problem (20 s):** ear tags fall off or get swapped, which leads to fake insurance
   claims, genuine farmers getting rejected, and stolen cattle that can't be proven.
2. **Register (30 s):** take 3 nose photos of a real cow, fill in owner, village and
   breed, and show the Pashu Aadhaar ID being created.
3. **Identify (30 s):** take a new photo from a different angle → "Match found" with
   the owner's details and the green ridge-match lines.
4. **Fraud check (15 s):** show a different cow → "Not registered, flag this claim."
5. **Results (15 s):** the accuracy screenshot from `evaluate.py`.
6. **Vision (10 s):** insurers, banks (cattle as loan collateral), dairy co-ops,
   government livestock schemes.

## Tips if accuracy is low on real photos

- Crop tighter to the nose. Background and nostrils confuse matching.
- Register 4–5 photos per cow instead of 3 (`--enroll 5`).
- Raise `MAX_FEATURES` in `pashu_core.py` (try 2000).
- Lower `RATIO` slightly (0.7) to be stricter.

## Future roadmap (for the pitch)

- Deep-learning model (published research reports up to 98.7% accuracy on this dataset)
- Automatic nose detection, so no manual cropping is needed
- Offline Android app for villages with no internet
- API for insurers, banks and government livestock schemes
