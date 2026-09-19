import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImagePreviewDialog } from "./ImagePreviewDialog";

const image = "data:image/jpeg;base64,aGVsbG8=";

describe("ImagePreviewDialog", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the selected image and returns it to the compose flow", async () => {
    const user = userEvent.setup();
    const onRequestChange = vi.fn();
    render(
      <ImagePreviewDialog image={image} onOpenChange={vi.fn()} onRequestChange={onRequestChange} />,
    );

    expect(screen.getByRole("img", { name: "Image générée en grand format" })).toHaveAttribute("src", image);
    await user.click(screen.getByRole("button", { name: "Demander une modification" }));

    expect(onRequestChange).toHaveBeenCalledWith(image);
  });

  it("uses a useful filename when downloading the generated image", async () => {
    const user = userEvent.setup();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {
      return undefined;
    });
    render(<ImagePreviewDialog image={image} onOpenChange={vi.fn()} onRequestChange={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Télécharger" }));

    expect(click).toHaveBeenCalledTimes(1);
    expect(document.querySelector('a[download="triton-image.jpg"]')).toBeNull();
  });

  it("notifies the parent when the preview is closed", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(<ImagePreviewDialog image={image} onOpenChange={onOpenChange} onRequestChange={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Fermer" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
