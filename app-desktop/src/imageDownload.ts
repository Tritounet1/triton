function imageExtension(src: string): string {
  const mediaType = /^data:image\/([^;,]+)/i.exec(src)?.[1] ?? "png";
  return mediaType === "jpeg" ? "jpg" : (mediaType.split("+")[0] ?? "png");
}

export function downloadImage(src: string) {
  const download = document.createElement("a");
  download.href = src;
  download.download = `triton-image.${imageExtension(src)}`;
  document.body.appendChild(download);
  download.click();
  download.remove();
}
