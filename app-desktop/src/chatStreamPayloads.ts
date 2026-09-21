export function stringField(data: Record<string, unknown>, field: string): string {
  const value = data[field];
  return typeof value === "string" ? value : "";
}

export function optionalStringField(data: Record<string, unknown>, field: string): string | undefined {
  const value = data[field];
  return typeof value === "string" ? value : undefined;
}
