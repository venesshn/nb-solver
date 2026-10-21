// Reads a box recording in the browser: nothing leaves the device.
import {
  BANNER_BOX,
  NAME_ROWS,
  SCAN_ROWS,
  TITLE_ROWS,
  assess,
  candidateTimes,
  countStars,
  levelImage,
  scaleBox,
  sharpness,
  textImage,
  visits,
} from "./readercore.js";

const TESSERACT = "https://cdn.jsdelivr.net/npm/tesseract.js@7.0.0/dist/tesseract.esm.min.js";
const SCAN_RATE = 2;

function toCanvas(image) {
  const canvas = document.createElement("canvas");
  canvas.width = image.width;
  canvas.height = image.height;
  canvas.getContext("2d").putImageData(new ImageData(image.data, image.width, image.height), 0, 0);
  return canvas;
}

function waitFor(target, event) {
  return new Promise((resolve, reject) => {
    const done = () => {
      target.removeEventListener(event, done);
      target.removeEventListener("error", fail);
      resolve();
    };
    const fail = () => {
      target.removeEventListener(event, done);
      reject(new Error("the video could not be decoded"));
    };
    target.addEventListener(event, done, { once: true });
    target.addEventListener("error", fail, { once: true });
  });
}

async function openVideo(file) {
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.preload = "auto";
  video.src = URL.createObjectURL(file);
  try {
    await waitFor(video, "loadeddata");
  } catch {
    throw new Error(
      "this browser can't decode the video. iPhone recordings are HEVC: open this page in Safari, or convert the recording to MP4 (H.264).",
    );
  }
  if (!video.videoWidth) throw new Error("the video has no picture this browser can show");
  return video;
}

// Brightness of every displayed frame while the video plays at double speed.
async function scan(video, onProgress) {
  const width = Math.max(32, Math.round(video.videoWidth / 8));
  const height = Math.max(64, Math.round(video.videoHeight / 8));
  const canvas = Object.assign(document.createElement("canvas"), { width, height });
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const top = Math.round((SCAN_ROWS[0] / 2556) * height);
  const bottom = Math.round((SCAN_ROWS[1] / 2556) * height);
  const samples = [];
  const measure = (time) => {
    ctx.drawImage(video, 0, 0, width, height);
    const data = ctx.getImageData(0, top, width, bottom - top).data;
    let total = 0;
    for (let p = 0; p < data.length; p += 4) total += data[p] + data[p + 1] + data[p + 2];
    samples.push([time, total / ((data.length / 4) * 3)]);
    onProgress(time / video.duration);
  };

  if ("requestVideoFrameCallback" in HTMLVideoElement.prototype) {
    await new Promise((resolve, reject) => {
      const frame = (_now, meta) => {
        measure(meta.mediaTime);
        if (!video.ended) video.requestVideoFrameCallback(frame);
      };
      video.requestVideoFrameCallback(frame);
      video.addEventListener("ended", resolve, { once: true });
      video.playbackRate = SCAN_RATE;
      video.play().catch(reject);
    });
  } else {
    // Older browsers: step through by seeking, slower but steady.
    for (let t = 0; t < video.duration; t += 1 / 15) {
      video.currentTime = t;
      await waitFor(video, "seeked");
      measure(t);
    }
  }
  video.pause();
  return samples.sort((a, b) => a[0] - b[0]);
}

async function grab(video, time, canvas, ctx) {
  video.currentTime = time;
  await waitFor(video, "seeked");
  ctx.drawImage(video, 0, 0);
  const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
  return { width: image.width, height: image.height, data: image.data };
}

function bannerThumb(page) {
  const box = scaleBox(BANNER_BOX, page.width, page.height);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round((box[2] - box[0]) / 2);
  canvas.height = Math.round((box[3] - box[1]) / 2);
  const full = toCanvas(page);
  canvas.getContext("2d").drawImage(full, box[0], box[1], box[2] - box[0], box[3] - box[1], 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.8);
}

export async function readRecording(file, allUnits, { status, progress }) {
  const units = allUnits.filter((u) => (u.rarity || 0) >= 4);
  status("Opening the video…");
  const video = await openVideo(file);
  if (Math.abs(video.videoWidth / video.videoHeight - 1180 / 2556) > 0.02) {
    status(`This video is ${video.videoWidth}×${video.videoHeight}; the reader was tuned on 1180×2556, so expect more pages to check.`);
  }

  status("Finding each unit (keep this tab open — it plays the video at double speed)…");
  const samples = await scan(video, (f) => progress(0.4 * f));
  const pages = visits(samples);
  if (!pages.length) throw new Error("no unit pages were found — is this a recording of the box detail pages?");

  status(`Found ${pages.length} units. Loading the text reader…`);
  const Tesseract = (await import(TESSERACT)).default;
  const text = await Tesseract.createWorker("eng");
  await text.setParameters({ tessedit_pageseg_mode: Tesseract.PSM.SINGLE_LINE });
  const digits = await Tesseract.createWorker("eng");
  await digits.setParameters({ tessedit_pageseg_mode: Tesseract.PSM.SINGLE_LINE, tessedit_char_whitelist: "0123456789/MAX" });

  const canvas = Object.assign(document.createElement("canvas"), { width: video.videoWidth, height: video.videoHeight });
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const readings = [];
  try {
    for (let n = 0; n < pages.length; n++) {
      status(`Reading unit ${n + 1} of ${pages.length}…`);
      let best = null;
      for (const time of candidateTimes(pages[n])) {
        const page = await grab(video, time, canvas, ctx);
        const score = sharpness(page);
        if (!best || score > best.score) best = { page, score };
      }
      const page = best.page;
      const rawName = (await text.recognize(toCanvas(textImage(page, NAME_ROWS)))).data.text.trim();
      const rawTitle = (await text.recognize(toCanvas(textImage(page, TITLE_ROWS)))).data.text.trim();
      const rawLevel = (await digits.recognize(toCanvas(levelImage(page)))).data.text.trim();
      const reading = assess({ rawName, rawTitle, rawLevel, stars: countStars(page) }, units);
      readings.push({ visit: n, banner: bannerThumb(page), ...reading });
      progress(0.4 + (0.6 * (n + 1)) / pages.length);
    }
  } finally {
    await text.terminate();
    await digits.terminate();
    URL.revokeObjectURL(video.src);
  }
  return readings;
}
