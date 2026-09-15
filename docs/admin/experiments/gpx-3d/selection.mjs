// The upstream module is unmodified. This thin adapter keeps one selection
// lane for clicks and a completely separate lane for the replay cursor.
import {registerEntityContext, selectEntityContext, getSelectedEntityContext, removeEntityContextsForLayer} from "./vendor/gods-eye-view/contextStore.mjs";

const LAYER = "scout-gpx-display-nodes";
export function createSelection(onSelected) {
  const carriers = new Map();
  const listener = event => { if (event.detail?.layerId === LAYER) onSelected(event.detail.node); };
  window.addEventListener("gev:entity-selected", listener);
  return {
    reset(nodes) {
      removeEntityContextsForLayer(LAYER);
      carriers.clear();
      for (const node of nodes) {
        const carrier = {};
        registerEntityContext(carrier, {id: node.id, layerId: LAYER, node});
        carriers.set(node.id, carrier);
      }
      onSelected(null);
    },
    select(id) { return selectEntityContext(carriers.get(id)); },
    current() { return getSelectedEntityContext()?.node || null; },
    dispose() { removeEntityContextsForLayer(LAYER); window.removeEventListener("gev:entity-selected", listener); },
  };
}
