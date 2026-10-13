const TILE_COLORS = ["#0f6fa8", "#c2410c", "#0e7c66", "#6d4aff", "#b42318", "#7a5b00"];

function projectColor(name: string): string {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return TILE_COLORS[hash % TILE_COLORS.length] ?? "#0f6fa8";
}

interface ProjectTileProps {
  name: string;
  size?: "sm" | "md";
}

export function ProjectTile({ name, size = "sm" }: ProjectTileProps) {
  const dimension = size === "sm" ? "h-[18px] w-[18px] text-[11px] rounded-[5px]" : "h-6 w-6 text-xs rounded-md";
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center font-semibold text-white ${dimension}`}
      style={{ backgroundColor: projectColor(name) }}
    >
      {name.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}
