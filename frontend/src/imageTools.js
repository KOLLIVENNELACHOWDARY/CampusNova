// Phone photos are often 5-12 MB; the server accepts at most 4 MB (Vercel's request limit). Shrink in the browser first.
export const MAX_SIDE = 1600

export async function shrinkImage(file, maxSide = MAX_SIDE, quality = 0.85) {
  if (!file.type.startsWith('image/')) throw new Error(`${file.name}: not an image`)
  const bitmap = await createImageBitmap(file) // respects EXIF orientation in modern browsers
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(bitmap.width * scale))
  canvas.height = Math.max(1, Math.round(bitmap.height * scale))
  canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', quality))
  if (!blob) throw new Error(`${file.name}: could not be processed`)
  return new File([blob], file.name.replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' })
}
