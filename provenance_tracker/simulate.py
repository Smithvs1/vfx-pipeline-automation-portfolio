"""Generate a realistic, fully fictional event log from a pretend gen-AI tool called "Lumen".

    python -m provenance_tracker.simulate -o sample_data/genai_events.jsonl --files-dir demo_downloads

The output deliberately includes a duplicate event, an event that references an unknown
asset, a download whose file hash doesn't match the generated asset (re-encoded file),
and events that arrive slightly out of order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

SHOWS = {"NVD": ["artist-03", "artist-07", "artist-11"], "HBL": ["artist-02", "artist-09"]}
TEXT_PROMPTS = {
    "NVD": ["frozen alien moon at dusk, twin suns low on the horizon, volumetric haze",
            "ice storm wall rolling over a research base, cinematic wide shot",
            "bioluminescent fungi pulsing inside a dark cave, macro lens",
            "escape pod streaking through atmosphere, plasma trail, night sky",
            "holographic star map projected over a metal table, blue light"],
    "HBL": ["1950s harbor town at night, neon reflections on wet cobblestones",
            "lighthouse beam sweeping through heavy fog, slow push in",
            "fishing boats returning at dawn, warm golden light, gentle waves",
            "vintage radio dial glowing in a dark kitchen, shallow depth of field"],
}
MODELS = {"image": "lumen-img-2", "video": "lumen-vid-3", "video_fast": "lumen-vid-4-turbo", "audio": "chorus-tts-1"}


def fake_bytes(asset_id: str) -> bytes:
    return f"FICTIONAL PLACEHOLDER CONTENT for {asset_id}\n".encode()


def sha(asset_id: str) -> str:
    return hashlib.sha256(fake_bytes(asset_id)).hexdigest()


class Sim:
    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)
        self.clock = datetime(2026, 11, 2, 9, 0, 0)
        self.events: list[dict] = []
        self.counters: dict[str, int] = {}
        self.downloaded: list[str] = []

    def _id(self, prefix: str) -> str:
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}_{self.counters[prefix]:04d}"

    def _tick(self) -> str:
        self.clock += timedelta(minutes=self.rng.randint(1, 25), seconds=self.rng.randint(0, 59))
        return self.clock.isoformat() + "Z"

    def _emit(self, type_: str, show: str, user: str, payload: dict, tool: str = "lumen") -> dict:
        ev = {"event_id": self._id("evt"), "type": type_, "timestamp": self._tick(), "tool": tool,
              "show": show, "user_id": user, "payload": payload}
        self.events.append(ev)
        return ev

    def upload(self, show, user, media_type, filename):
        aid = self._id("upl")
        self._emit("asset.uploaded", show, user,
                   {"asset_id": aid, "media_type": media_type, "sha256": sha(aid), "filename": filename})
        return aid

    def prompt(self, show, user, modality, text=None, asset_id=None, tool="lumen"):
        pid = self._id("prm")
        payload = {"prompt_id": pid, "modality": modality}
        if text:
            payload["text"] = text
        if asset_id:
            payload["asset_id"] = asset_id
        self._emit("prompt.submitted", show, user, payload, tool=tool)
        return pid

    def generate(self, show, user, prompt_ids, media_type, model, **params):
        gid, aid = self._id("gen"), self._id("out")
        ext = {"image": "png", "video": "mp4", "audio": "wav"}[media_type]
        params.setdefault("seed", self.rng.randint(1, 2**31))
        self._emit("generation.completed", show, user, {
            "generation_id": gid, "prompt_ids": prompt_ids, "model": model, "params": params,
            "output": {"asset_id": aid, "media_type": media_type, "sha256": sha(aid),
                       "filename": f"{show}_{gid}.{ext}"},
        }, tool="chorus" if model.startswith("chorus") else "lumen")
        return aid

    def download(self, show, user, asset_id, filename=None, tampered=False):
        did = self._id("dl")
        digest = hashlib.sha256(b"re-encoded " + fake_bytes(asset_id)).hexdigest() if tampered else sha(asset_id)
        self._emit("asset.downloaded", show, user, {
            "download_id": did, "asset_id": asset_id, "sha256": digest,
            "filename": filename or f"{asset_id}.bin", "size_bytes": len(fake_bytes(asset_id)),
        })
        if not tampered:
            self.downloaded.append(asset_id)

    # ------ scenarios ------

    def hero_chain(self):
        """Text -> image -> video, plus an uploaded voice reference: a 3-generation lineage."""
        show, user = "NVD", "artist-07"
        p1 = self.prompt(show, user, "text", TEXT_PROMPTS["NVD"][0])
        img = self.generate(show, user, [p1], "image", MODELS["image"], width=2048, height=858)
        p2 = self.prompt(show, user, "image", asset_id=img)
        p3 = self.prompt(show, user, "text", "slow dolly forward across the ice, light snow falling")
        vid = self.generate(show, user, [p2, p3], "video", MODELS["video"], duration_s=6, fps=24)
        voice = self.upload(show, "artist-03", "audio", "temp_vo_scene12_take3.wav")
        p4 = self.prompt(show, "artist-03", "audio", asset_id=voice)
        p5 = self.prompt(show, "artist-03", "video", asset_id=vid)
        final = self.generate(show, "artist-03", [p5, p4], "video", MODELS["video_fast"], duration_s=6,
                              motion_strength=0.4)
        self.download(show, "artist-03", final, "NVD_101_ARR_0010_previs_v003.mp4")
        self.download(show, "artist-11", vid, "NVD_101_ARR_0010_bg_plate_v001.mp4")

    def random_chain(self, show):
        user = self.rng.choice(SHOWS[show])
        if self.rng.random() < 0.3:
            ref = self.upload(show, user, "image", f"moodboard_ref_{self.rng.randint(1, 40):02d}.jpg")
            prompts = [self.prompt(show, user, "image", asset_id=ref),
                       self.prompt(show, user, "text", self.rng.choice(TEXT_PROMPTS[show]))]
            out = self.generate(show, user, prompts, "video", MODELS["video"], duration_s=self.rng.choice([4, 6, 8]))
        else:
            p = self.prompt(show, user, "text", self.rng.choice(TEXT_PROMPTS[show]))
            out = self.generate(show, user, [p], "image", MODELS["image"])
            if self.rng.random() < 0.5:
                p2 = self.prompt(show, user, "image", asset_id=out)
                out = self.generate(show, user, [p2], "video", self.rng.choice([MODELS["video"], MODELS["video_fast"]]),
                                    duration_s=4)
        if self.rng.random() < 0.45:
            self.download(show, user, out)

    def run(self, n_random: int = 18) -> list[dict]:
        self.hero_chain()
        for _ in range(n_random):
            self.random_chain(self.rng.choice(list(SHOWS)))
        # temp-track narration generated from a script line
        line = "Narrator, warm and low: 'The light never failed. Until that night.'"
        p = self.prompt("HBL", "artist-09", "text", line, tool="chorus")
        vo = self.generate("HBL", "artist-09", [p], "audio", MODELS["audio"], voice="narrator-b")
        self.download("HBL", "artist-09", vo, "HBL_102_temp_narration.wav")
        # data-quality cases
        some_video = next(e["payload"]["output"]["asset_id"] for e in self.events
                          if e["type"] == "generation.completed" and e["payload"]["output"]["media_type"] == "video"
                          and e["show"] == "HBL")
        self.download("HBL", "artist-02", some_video, "HBL_lighthouse_FINAL_reencode.mov", tampered=True)
        self.events.append(dict(self.events[5]))  # duplicate delivery
        self._emit("prompt.submitted", "NVD", "artist-11", {"prompt_id": "prm_9999", "modality": "image",
                                                             "asset_id": "upl_missing"})
        # simulate late delivery: swap two adjacent events in the file (timestamps stay correct)
        i = len(self.events) // 2
        self.events[i], self.events[i + 1] = self.events[i + 1], self.events[i]
        return self.events


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-o", "--output", type=Path, default=Path("sample_data/genai_events.jsonl"))
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--files-dir", type=Path, help="also write placeholder files for downloaded assets here")
    args = p.parse_args(argv)
    sim = Sim(args.seed)
    events = sim.run()
    args.output.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    print(f"wrote {len(events)} events to {args.output}")
    if args.files_dir:
        args.files_dir.mkdir(parents=True, exist_ok=True)
        for aid in dict.fromkeys(sim.downloaded):
            (args.files_dir / f"{aid}.bin").write_bytes(fake_bytes(aid))
        print(f"wrote {len(set(sim.downloaded))} placeholder files to {args.files_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
