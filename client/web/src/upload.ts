/** 图片上传：先把照片压到浏览器能接受的尺寸，再 POST 到服务端的图片服务。 */

const MAX_EDGE = 1280;
const JPEG_QUALITY = 0.82;
const MAX_RAW_GIF = 2 * 1024 * 1024;

export interface UploadedImage {
  file: string;
  url: string;
  bytes: number;
  mime: string;
}

export async function uploadImage(file: File, imageBase: string): Promise<UploadedImage> {
  if (!imageBase) throw new Error('图片服务地址还没就绪（桥没握手成功）');
  const blob = await shrink(file);
  const res = await fetch(`${imageBase}/upload`, {
    method: 'POST',
    headers: { 'Content-Type': blob.type },
    body: blob,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`服务端拒绝（${res.status}）${detail.slice(0, 120)}`);
  }
  const payload = (await res.json()) as UploadedImage;
  if (!payload?.file) throw new Error('服务端没有返回文件名');
  return payload;
}

/** 等比缩到最大边 1280 并转 JPEG；GIF 保留原图（重新编码会丢动画） */
async function shrink(file: File): Promise<Blob> {
  if (file.type === 'image/gif' && file.size <= MAX_RAW_GIF) return file;

  const bitmap = await loadBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const width = Math.max(1, Math.round(bitmap.width * scale));
  const height = Math.max(1, Math.round(bitmap.height * scale));

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('浏览器不支持 canvas，无法压缩图片');
  ctx.drawImage(bitmap as CanvasImageSource, 0, 0, width, height);
  if ('close' in bitmap) (bitmap as ImageBitmap).close();

  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY),
  );
  if (!blob) throw new Error('图片编码失败');
  return blob;
}

async function loadBitmap(file: File): Promise<ImageBitmap | HTMLImageElement> {
  if ('createImageBitmap' in window) {
    try {
      return await createImageBitmap(file);
    } catch {
      /* 走下面的 <img> 回退 */
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return img;
  } finally {
    URL.revokeObjectURL(url);
  }
}
