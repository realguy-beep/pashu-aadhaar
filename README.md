# Pashu Aadhaar: nose-print ID for cattle

**Live demo: https://pashu-aadhaar.onrender.com** (free hosting; the first load after idle takes about 1 minute)

Every cow's muzzle (nose) has a unique pattern of ridges and beads, like a human fingerprint.
Pashu Aadhaar registers an animal from 2–3 phone photos of its nose and later identifies it from
one new photo. No ear tag is needed, and no AI training is needed to add a new animal.

It is meant to sit beside the government's 12-digit ear-tag Pashu Aadhaar (Bharat Pashudhan),
not replace it: the ear tag identifies a tag, this identifies the animal.

## Quick start

Install Python 3.9 or newer, then in this folder run:

```
pip install -r requirements.txt
python app.py
```

Open **http://localhost:5000**. To use a phone camera, connect the phone to the same Wi-Fi and
open `http://<laptop-IP>:5000` (on Windows, find the IP with `ipconfig`).

After changing any code or template, stop the app (Ctrl+C) and start it again.

### The first administrator

- **Local:** when no administrator exists, `python app.py` prints a one-time setup link in the
  terminal. The account you create through that link becomes the administrator. You can also run
  `python app.py create-admin`.
- **Render:** set `PASHU_ADMIN_USER` and `PASHU_ADMIN_PASSWORD` in the Render dashboard before the
  first start.

## Using the app

| Page | What it does |
|---|---|
| Identify | Take or choose one nose photo, adjust the crop, and the whole registry is searched. Shows the match with a picture of the matching ridge points, or "Not registered". |
| Register | Add 2–5 nose photos plus owner, mobile, village, animal, breed, ear-tag number and insurance status. Blocked automatically if the animal is already registered. |
| My animals / Registry | Your animals, with search. Administrators see every animal. |
| Account | Profile and photo, change password, recovery codes, signed-in devices, sign out. |
| Admin | Users (disable, make admin, issue a password-reset code) and the activity log. |

The language switch (English / हिन्दी) is at the top of every page and is remembered for each
account. All text lives in `i18n.py`.

### Who can see what

- Every animal belongs to the account that registered it. Normal users see only their own animals;
  administrators see all of them.
- **Identify** and the **duplicate check** always search the whole registry, so fraud checks work
  across accounts. When the match belongs to someone else, the owner's name, phone and ear tag are
  hidden.
- The 20 demo cows, and any animal registered before accounts were added, have no owner account.
  Only administrators see them until an administrator gives them an owner.

### "Already registered", but my list is empty

This means the animal really is in the registry, but under a different account, for example one
you made earlier. Either sign in to that account, or have an administrator open the record
(Registry, then the animal) and use **Transfer** to move it to the right account. Every transfer
is written to the activity log.

### Forgotten passwords

1. **Recovery codes.** Every new account is shown 8 one-time codes right after sign-up (Copy and
   Download buttons). Use one at **Forgot password?** on the sign-in page. Make a fresh set any time
   from **Account, Account recovery**; this cancels the old ones. Accounts made before this feature
   have no codes until they make some.
2. **Administrator code.** An administrator clicks **Reset password** next to the user on the Admin
   page and passes on the one-time code (valid for 1 hour) after checking who they are.
3. **Locked-out administrator.** On the computer running the app:
   `python app.py reset-password <username>`

Every reset signs the account out on all devices.

## Try the demo

A fresh install loads 20 demo cows (owners and villages are fictional; the nose photos come from
the public dataset below). Sign in as the administrator, then:

- **Identify** with `demo_photos/registered/PA-5C738588_Ramesh_1.jpg`: match, Ramesh Patel's cow
- **Identify** with any photo in `demo_photos/unregistered/`: Not registered
- **Register** with `demo_photos/duplicate/same_as_Ramesh_1.jpg`: duplicate blocked
- **Identify** with `demo_photos/retake/blurry_1.jpg`: asks for a retake

In the crop dialog, leave the box at its default size for these small demo photos; zooming in
tightly on a small photo can make it too blurry to read.

## Security

- Passwords stored as scrypt hashes; at least 10 characters with letters and numbers; common
  passwords and passwords containing the username are refused.
- Sign-in throttling per username and network, per username, and per network. It is safe against
  parallel guessing, and an attacker cannot lock a real user out from another network.
- Server-side sessions, revoked on sign-out, password change, password reset, or when an
  administrator disables the account; 30-minute idle and 12-hour absolute limits; a list of
  signed-in devices with "Sign out other devices".
- Recovery and reset codes stored only as keyed hashes, single use, throttled; administrator codes
  expire after 1 hour.
- A secret token plus an Origin check on every form; a strict Content-Security-Policy with no inline
  scripts or styles; HttpOnly, SameSite cookies (Secure and HSTS on HTTPS); open-redirect
  protection.
- Uploads limited to JPEG, PNG and WebP, with size and pixel-count limits; every image is
  re-encoded, which strips hidden metadata.
- Per-user rate limits on Identify and Register; an administrator activity log.
- Static files carry a version stamp, so browsers always load the current scripts after an update.

## Files

| File | What it does |
|---|---|
| `pashu_core.py` | Matching engine: photo clean-up, ridge features (SIFT), two-stage search, geometric check (RANSAC), quality gate, registry on disk |
| `app.py` | Web app: accounts, pages, security, password reset, ownership transfer |
| `i18n.py` | English and Hindi text for the whole interface |
| `templates/` | Page templates |
| `static/` | `style.css`, `app.js` (crop, upload, password tools), Cropper.js, icon |
| `evaluate.py` | Measures accuracy on a dataset; gives the numbers for the application |
| `seed_demo.py` | Builds the demo registry (`demo_db/`, 20 cows) and test photos (`demo_photos/`) from the public dataset |
| `demo_photos/` | `registered/` (should match), `unregistered/` (should be rejected), `duplicate/` (registration is blocked), `retake/` (blurry) |
| `render.yaml` | One-click deploy configuration for Render.com |
| `db/` | Registered animals (not in git) |
| `instance/` | Accounts database, profile photos and the secret key (not in git) |

## Measure accuracy

Download the public dataset, "Beef Cattle Muzzle/Noseprint database" (4,923 photos of 268 cattle):
https://zenodo.org/record/6324361. Unzip it; it has one folder per animal. Then:

```
python evaluate.py path/to/BeefCattle_Muzzle_database --cows 100 --unknown 168
```

It prints rank-1 accuracy, correct identification and wrong acceptance at several thresholds, and
the search time. Set `DEFAULT_THRESHOLD` in `pashu_core.py` to the suggested value.

> **Results** (100 registered cattle, 168 never registered, 632 test photos, threshold 15):
> rank-1 accuracy 97.4%, correct identification 96.7%, 128 ms per search, about 6% of photos sent
> back for a retake. All 4 apparent errors were the same animal filed under two IDs in the dataset
> itself (4451/4454 and 5407/6011), so there were no genuine false matches. Use `--show-errors` to
> list them.

## Collect field data (next step)

The results above are on beef cattle from one public dataset. Before relying on it for real
claims, collect Indian animals:

- 100–200 cows and buffalo from a dairy co-operative or gaushala, with the owners' permission.
- Two visits a few weeks apart: 3 photos to register at the first, 3–5 to test at the second.
- Ordinary phones in daylight; fill the frame with the nose.
- Keep some animals unregistered as impostors, then run `evaluate.py` on the folder.

## Tips if accuracy is low on real photos

- Get close so the nose fills the photo; background and nostrils confuse matching.
- Register 4–5 photos per animal instead of 3 (`--enroll 5` in `evaluate.py`).
- Raise `MAX_FEATURES` in `pashu_core.py` (try 2000).
- Lower `RATIO` slightly (0.7) to be stricter.

## Deploy (free, on Render)

1. Push this folder to GitHub.
2. On https://render.com: **New, Blueprint**, and pick the repository. Render reads `render.yaml`.
3. Set `PASHU_ADMIN_USER` and `PASHU_ADMIN_PASSWORD`, then wait about 5 minutes for the build.

The free plan sleeps after 15 minutes idle, so the first visit takes about a minute (open it before
a demo). Its disk resets on every redeploy or restart, which erases accounts and new
registrations; a real deployment needs a persistent disk or database.

## Demo video plan (about 2 minutes)

1. **Problem (20 s):** ear tags fall off or get swapped, which leads to fake insurance claims,
   genuine farmers being rejected, and stolen cattle that can't be proven.
2. **Register (30 s):** take 3 nose photos of a real cow, fill in owner, village and breed, and show
   the Pashu Aadhaar ID being created.
3. **Identify (30 s):** take a new photo from a different angle; show "Match found" with the
   ridge-match picture.
4. **Fraud check (15 s):** a different cow gives "Not registered"; a second registration of the same
   cow is blocked.
5. **Results (15 s):** the accuracy output from `evaluate.py`.
6. **Vision (10 s):** insurers, banks (cattle as loan collateral), dairy co-operatives, government
   livestock schemes.

## Known limitations and roadmap

- Not yet tested on Indian breeds or buffalo, on field photos, or on the same animal weeks apart.
- No check that a live animal is in front of the camera (a printed photo could be used).
- The user crops by hand; automatic nose detection is planned.
- Built for hundreds of animals on one server; millions need a database and a faster search.
- Online only; an offline Android app is planned.
- Password reset by SMS needs an SMS provider; recovery codes and administrator codes work today.
- Next: link each record to the animal's 12-digit Bharat Pashudhan ID.

## Credits

Nose photos: *Beef Cattle Muzzle/Noseprint database for individual identification*, Zenodo record
[6324361](https://zenodo.org/record/6324361), licensed CC-BY 4.0.
