/** 图片上传：先把照片压到浏览器能接受的尺寸，再 POST 到服务端的图片服务。 */

const MAX_EDGE = 1280;
const JPEG_QUALITY = 0.82;
const MAX_RAW_GIF = 2 * 1024 * 1024;

export interface UploadedAttachment {
  file: string;
  name: string;
  kind: 'image' | 'file';
  url: string;
  bytes: number;
  mime: string;
}

/** 与上传统一入口：图片先压缩，其它文件原样上传（普通文件不动，免得压坏） */
export async function uploadAttachment(
  file: File,
  imageBase: string,
): Promise<UploadedAttachment> {
  if (!imageBase) throw new Error('附件服务地址还没就绪（桥没握手成功）');
  const isImage = file.type.startsWith('image/');
  const blob = isImage ? await shrink(file) : file;
  const headers: Record<string, string> = { 'Content-Type': blob.type || 'application/octet-stream' };
  // 图片走 Content-Type 判定，其它文件靠 X-Filename 认后缀和原名
  if (!isImage) headers['X-Filename'] = encodeURIComponent(file.name);

  const res = await fetch(`${imageBase}/upload`, { method: 'POST', headers, body: blob });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`服务端拒绝（${res.status}）${detail.slice(0, 120)}`);
  }
  const payload = (await res.json()) as UploadedAttachment;
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
