const DB_NAME = 'scout-trip-notebook-v1';
export async function openStore() {
  return new Promise((resolve,reject) => {
    const request = indexedDB.open(DB_NAME,1);
    request.onupgradeneeded = () => {
      const db = request.result;
      db.createObjectStore('drafts',{keyPath:'id'});
      db.createObjectStore('packages',{keyPath:'key'});
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
export function all(db, store) {
  return new Promise((resolve,reject) => {const request=db.transaction(store).objectStore(store).getAll();request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
}
export async function saveDraft(db, snapshot, draft) {
  const next = structuredClone(draft);
  next.revision += 1;
  next.updated_at = new Date().toISOString();
  return new Promise((resolve,reject) => {
    const tx = db.transaction(['drafts','packages'],'readwrite');
    let conflict = false;
    const store=tx.objectStore('drafts');
    const current = store.get(draft.id);
    current.onsuccess = () => {
      if ((current.result?.revision || 0) !== draft.revision) {conflict=true;tx.abort();return;}
      tx.objectStore('packages').put({key:`${snapshot.project_id}:${snapshot.version}`,snapshot});
      store.put(next);
    };
    tx.oncomplete = () => resolve(next);
    tx.onabort = () => reject(new Error(conflict ? '另一個分頁已有新版本。請重新讀取，或將目前內容另存新草稿。' : '保存失敗：空間不足或儲存不可用。請匯出備份，未顯示保存成功。'));
    tx.onerror = () => {};
  });
}
export function savePackage(db,snapshot) {
  return new Promise((resolve,reject) => {const tx=db.transaction('packages','readwrite');tx.objectStore('packages').put({key:`${snapshot.project_id}:${snapshot.version}`,snapshot});tx.oncomplete=()=>resolve();tx.onabort=()=>reject(tx.error);});
}
