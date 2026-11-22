#!/usr/bin/env python3
"""스튜디오 매물 앱 데이터 내보내기.

매물 문서와 사진을 앱 코드로 암호화해 data/ 폴더에 씁니다. 공개 저장소에는 암호화된 파일만 올라갑니다.

  python3 export.py --code 앱코드 --listings 문서폴더 --meta status.json --photos 사진폴더 --out ../data
                    [--rooms-listings 방문서폴더 --rooms-meta rooms.json --rooms-conditions 문구]

--listings  스튜디오 매물 문서 JSON 폴더 (파일 이름이 문서 id)
--meta      스튜디오 상태 문서 JSON
--photos    <사진id>.jpg 파일이 있는 폴더. 이미 data/p에 있는 사진은 없어도 됩니다.
--conditions  스튜디오 탭 맨 위에 보여 줄 조건 문구
--rooms-*   '방' 탭(위반건축물 방 찾기) 문서 폴더, 상태 문서, 조건 문구.
            주지 않으면 지난번 board.bin에 있던 방 탭 내용과 사진을 그대로 둡니다.
"""
import argparse
import json
import os
import pathlib
import re
import sys
import hashlib

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


def load_docs(folder):
    docs = []
    for path in sorted(pathlib.Path(folder).glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["id"] = path.stem
        docs.append(doc)
    return docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default=os.environ.get("STUDIO_CODE", ""))
    ap.add_argument("--listings", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--photos", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--conditions", default="")
    ap.add_argument("--rooms-listings", default="")
    ap.add_argument("--rooms-meta", default="")
    ap.add_argument("--rooms-conditions", default="")
    args = ap.parse_args()
    if len(clean_code(args.code)) < 12:
        sys.exit("앱 코드가 없습니다")

    key = derive(args.code)
    out = pathlib.Path(args.out)
    photo_out = out / "p"
    photo_out.mkdir(parents=True, exist_ok=True)
    source = pathlib.Path(args.photos) if args.photos else None
    target = out / "board.bin"

    old = None
    try:
        if target.exists():
            old = json.loads(unseal(key, target.read_bytes()))
    except Exception:
        old = None

    listings = load_docs(args.listings)
    if not listings:
        sys.exit("매물 문서가 없습니다")

    rooms = None
    if args.rooms_meta and pathlib.Path(args.rooms_meta).exists():
        rooms_meta = json.loads(pathlib.Path(args.rooms_meta).read_text(encoding="utf-8"))
        if args.rooms_conditions:
            rooms_meta["conditions"] = args.rooms_conditions
        room_docs = load_docs(args.rooms_listings) if args.rooms_listings and pathlib.Path(args.rooms_listings).exists() else []
        rooms = {"meta": rooms_meta, "listings": room_docs}
        fresh_rooms = True
    elif old and isinstance(old.get("rooms"), dict):
        # 이번에 방 탭 문서를 못 읽었으면 지난번 내용을 그대로 둔다
        rooms = old["rooms"]
        fresh_rooms = False
    else:
        fresh_rooms = False

    added, resized, missing, wanted = 0, 0, [], set()
    sets = [listings] + ([rooms["listings"]] if rooms else [])
    for docs in sets:
        for doc in docs:
            kept = []
            for pid in doc.get("photos") or []:
                if not re.fullmatch(r"[0-9a-f]{32}", str(pid)):
                    missing.append(str(pid))
                    continue
                dest = photo_out / f"{pid}.bin"
                found = None
                if source:
                    found = next((p for p in source.glob(f"{pid}*") if p.is_file() and p.suffix.lower() != ".bin"), None)
                if dest.exists():
                    # 원본을 줄였으면(앱 갱신 스크립트가 긴 쪽 1280px로 줄임) 예전에 크게 암호화해 둔 사진을 줄인 것으로 바꾼다.
                    # 암호문은 원본보다 28바이트 크다. 2KB 넘게 더 크면 원본이 줄어든 것이다
                    if found and dest.stat().st_size > found.stat().st_size + 28 + 2048:
                        dest.write_bytes(seal(key, found.read_bytes()))
                        resized += 1
                else:
                    if not found:
                        missing.append(pid)
                        continue
                    dest.write_bytes(seal(key, found.read_bytes()))
                    added += 1
                wanted.add(pid)
                kept.append(pid)
            doc["photos"] = kept

    removed = 0
    for f in photo_out.glob("*.bin"):
        if f.stem not in wanted:
            f.unlink()
            removed += 1

    meta = json.loads(pathlib.Path(args.meta).read_text(encoding="utf-8"))
    if args.conditions:
        meta["conditions"] = args.conditions
    payload = {"meta": meta, "listings": listings}
    if rooms:
        payload["rooms"] = rooms
    board = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    # 내용이 그대로면 다시 쓰지 않는다. 다시 쓰면 암호문이 매번 달라져 바뀐 것 없이 커밋이 생긴다.
    same = old is not None and json.dumps(old, ensure_ascii=False).encode("utf-8") == board
    if not same:
        target.write_bytes(seal(key, board))

    check = json.loads(unseal(key, target.read_bytes()))
    if check["meta"].get("runId") != meta.get("runId"):
        sys.exit("암호화 확인 실패")
    n_rooms = len(rooms["listings"]) if rooms else 0
    print(f"스튜디오 매물 {len(listings)}건, 방 매물 {n_rooms}건{'' if fresh_rooms or not rooms else '(지난번 내용 유지)'}, 사진 {len(wanted)}장 (새로 {added}, 줄여 바꿈 {resized}, 삭제 {removed}, 없음 {len(missing)})")
    if same and not added and not removed and not resized:
        print("변경 없음")
    for pid in missing:
        print(f"사진 없음: {pid}")


if __name__ == "__main__":
    main()
