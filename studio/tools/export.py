#!/usr/bin/env python3
"""스튜디오 매물 앱 데이터 내보내기.

매물 문서와 사진을 앱 코드로 암호화해 data/ 폴더에 씁니다. 공개 저장소에는 암호화된 파일만 올라갑니다.

  python3 export.py --code 앱코드 --listings 문서폴더 --meta status.json --photos 사진폴더 --out ../data

--listings  매물 문서 JSON 폴더 (파일 이름이 문서 id)
--meta      상태 문서 JSON
--photos    <사진id>.jpg 파일이 있는 폴더. 이미 data/p에 있는 사진은 없어도 됩니다.
--conditions  앱 맨 위에 보여 줄 조건 문구
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SALT = b"ketaku-studio-v1"
ROUNDS = 200000


def clean_code(code):
    return re.sub(r"[^a-z0-9]", "", code.lower())


def derive(code):
    return hashlib.pbkdf2_hmac("sha256", clean_code(code).encode(), SALT, ROUNDS, 32)


def seal(key, data):
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def unseal(key, blob):
    return AESGCM(key).decrypt(blob[:12], blob[12:], None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default=os.environ.get("STUDIO_CODE", ""))
    ap.add_argument("--listings", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--photos", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--conditions", default="")
    args = ap.parse_args()
    if len(clean_code(args.code)) < 12:
        sys.exit("앱 코드가 없습니다")

    key = derive(args.code)
    out = pathlib.Path(args.out)
    photo_out = out / "p"
    photo_out.mkdir(parents=True, exist_ok=True)
    source = pathlib.Path(args.photos) if args.photos else None

    listings = []
    for path in sorted(pathlib.Path(args.listings).glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["id"] = path.stem
        listings.append(doc)
    if not listings:
        sys.exit("매물 문서가 없습니다")

    added, missing, wanted = 0, [], set()
    for doc in listings:
        kept = []
        for pid in doc.get("photos") or []:
            if not re.fullmatch(r"[0-9a-f]{32}", str(pid)):
                missing.append(str(pid))
                continue
            target = photo_out / f"{pid}.bin"
            if not target.exists():
                found = None
                if source:
                    found = next((p for p in source.glob(f"{pid}*") if p.is_file()), None)
                if not found:
                    missing.append(pid)
                    continue
                target.write_bytes(seal(key, found.read_bytes()))
                added += 1
            wanted.add(pid)
            kept.append(pid)
        doc["photos"] = kept

    removed = 0
    for old in photo_out.glob("*.bin"):
        if old.stem not in wanted:
            old.unlink()
            removed += 1

    meta = json.loads(pathlib.Path(args.meta).read_text(encoding="utf-8"))
    if args.conditions:
        meta["conditions"] = args.conditions
    board = json.dumps({"meta": meta, "listings": listings}, ensure_ascii=False).encode("utf-8")
    target = out / "board.bin"
    # 내용이 그대로면 다시 쓰지 않는다. 다시 쓰면 암호문이 매번 달라져 바뀐 것 없이 커밋이 생긴다.
    try:
        same = target.exists() and unseal(key, target.read_bytes()) == board
    except Exception:
        same = False
    if not same:
        target.write_bytes(seal(key, board))

    if json.loads(unseal(key, target.read_bytes()))["meta"].get("runId") != meta.get("runId"):
        sys.exit("암호화 확인 실패")
    print(f"매물 {len(listings)}건, 사진 {len(wanted)}장 (새로 {added}, 삭제 {removed}, 없음 {len(missing)})")
    if same and not added and not removed:
        print("변경 없음")
    for pid in missing:
        print(f"사진 없음: {pid}")


if __name__ == "__main__":
    main()
