import { previewImageUrl } from "../../api";

export function ImagePreview({ path }: { path: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "center" }}>
      <img
        src={previewImageUrl(path)}
        alt={path}
        style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", borderRadius: 8 }}
      />
    </div>
  );
}
