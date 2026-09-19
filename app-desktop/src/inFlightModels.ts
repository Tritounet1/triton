/** Model chosen for a request that has started but has not completed yet.
 *
 * New conversations temporarily use an empty key.  Keeping these small state
 * transitions outside App makes the hand-off to the server-assigned session
 * id deterministic and independently testable.
 */
export type InFlightModels = Record<string, string>;

export function setInFlightModel(
  previous: InFlightModels,
  key: string,
  model: string | null,
): InFlightModels {
  if (model) {
    return previous[key] === model ? previous : { ...previous, [key]: model };
  }
  if (!(key in previous)) return previous;
  return Object.fromEntries(
    Object.entries(previous).filter(([candidate]) => candidate !== key),
  );
}

export function moveInFlightModel(
  previous: InFlightModels,
  oldKey: string,
  newKey: string,
): InFlightModels {
  if (!(oldKey in previous) || oldKey === newKey) return previous;
  const model = previous[oldKey];
  const remaining = Object.fromEntries(
    Object.entries(previous).filter(([candidate]) => candidate !== oldKey),
  );
  return model ? { ...remaining, [newKey]: model } : remaining;
}
