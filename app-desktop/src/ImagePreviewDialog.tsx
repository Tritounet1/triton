import { Button } from "@astryxdesign/core/Button";
import { Dialog } from "@astryxdesign/core/Dialog";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { DownloadIcon, ImageIcon, XIcon } from "./icons";
import { downloadImage } from "./imageDownload";

interface ImagePreviewDialogProps {
  image: string | null;
  onOpenChange: (isOpen: boolean) => void;
  onRequestChange: (image: string) => void;
}

/** Full-size generated-image preview, kept separate from the chat state. */
export function ImagePreviewDialog({
  image,
  onOpenChange,
  onRequestChange,
}: ImagePreviewDialogProps) {
  return (
    <Dialog
      isOpen={image !== null}
      onOpenChange={onOpenChange}
      purpose="info"
      width={980}
      maxHeight="90dvh"
      padding={0}
      aria-label="Aperçu de l’image générée"
    >
      {image && (
        <div className="flex max-h-[90dvh] flex-col">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <Text size="sm" weight="semibold">
              Image générée
            </Text>
            <IconButton
              label="Fermer"
              icon={<XIcon />}
              variant="ghost"
              size="sm"
              onClick={() => {
                onOpenChange(false);
              }}
            />
          </div>
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto bg-surface-raised p-4">
            <img
              src={image}
              alt="Image générée en grand format"
              className="max-h-[68dvh] max-w-full object-contain"
            />
          </div>
          <div className="flex flex-wrap justify-end gap-2 border-t border-border px-4 py-3">
            <Button
              label="Télécharger"
              icon={<DownloadIcon />}
              variant="secondary"
              onClick={() => {
                downloadImage(image);
              }}
            />
            <Button
              label="Demander une modification"
              icon={<ImageIcon />}
              variant="primary"
              onClick={() => {
                onRequestChange(image);
              }}
            />
          </div>
        </div>
      )}
    </Dialog>
  );
}
