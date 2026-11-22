"""Распознавание речи GigaAM-v3 (Сбер) — запускается отдельным процессом питоном VoiceType,
где уже стоят gigaam и torch, а модель лежит в его папке models.

    python gigaam_worker.py <папка моделей>
    затем в stdin: <аудио.npy 16 кГц float32>|<куски.json [[начало, конец], …]>|<ответ.json>

Пишет в stdout строки «P 0.42» (прогресс), в ответ — слова [{"s", "e", "w", "p"}] с временем по всей записи.
"""
import json
import sys


def main() -> int:
    """Модель грузится один раз; задания приходят строками в stdin: «аудио.npy|куски.json|ответ.json»."""
    models_dir = sys.argv[1]
    import torch

    import gigaam

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = gigaam.load_model("v3_e2e_rnnt", device=dev, download_root=models_dir)
    model.eval()
    print("READY", flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line == "QUIT":
            break
        try:
            job(model, dev, *line.split("|"))
            print("DONE", flush=True)
        except Exception as e:  # noqa: BLE001
            print("ERR " + " ".join(str(e).split())[:400], flush=True)
    return 0


def job(model, dev, audio_path, segs_path, out_path):
    import numpy as np
    import torch

    audio = np.load(audio_path, mmap_mode="r")
    with open(segs_path, encoding="utf-8") as f:
        segs = json.load(f)
    sr = 16000
    words = []
    batch = 8
    for i in range(0, len(segs), batch):
        part = segs[i:i + batch]
        wavs = [torch.from_numpy(np.ascontiguousarray(audio[int(a * sr):int(b * sr)], dtype=np.float32)) for a, b in part]
        lens = torch.tensor([len(w) for w in wavs])
        pad = torch.zeros(len(wavs), int(lens.max()))
        for k, w in enumerate(wavs):
            pad[k, :len(w)] = w
        with torch.inference_mode():
            enc, enc_len = model.forward(pad.to(dev).to(model._dtype), lens.to(dev))
            dec = model._decode(enc, enc_len, lens.to(dev), True)
        for (a, _b), (_text, ws) in zip(part, dec):
            for w in ws or []:
                t = (w.text or "").strip()
                if t:
                    words.append({"s": round(a + w.start, 3), "e": round(a + w.end, 3), "w": t, "p": 1.0})
        print(f"P {min(1.0, (i + len(part)) / len(segs)):.3f}", flush=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
