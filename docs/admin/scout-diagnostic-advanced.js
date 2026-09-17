/* Executable, isolated replays of trusted Dashboard functions. Synthetic storage only; no user records or network. */
(function (root) {
  "use strict";
  const requireValue = (value, message) => { if (!value) throw new Error(message); };
  function compile(sources, names, environment) {
    for (const name of names) requireValue(typeof sources[name] === "string" && sources[name].includes(`function ${name}(`), `Missing production source: ${name}`);
    // Sources are supplied by the Dashboard itself, never accepted from API/model/user content.
    return Function(...Object.keys(environment), `"use strict";\n${names.map(name => sources[name]).join("\n")}\nreturn {${names.join(",")}};`)(...Object.values(environment));
  }
  function memoryDatabase() {
    const stores = {keys: new Map(), offline_intents: new Map()};
    const database = {
      close() {},
      transaction(name) {
        const transaction = {error: null};
        let scheduled = false;
        const complete = () => {
          if (scheduled) return;
          scheduled = true;
          setTimeout(() => transaction.oncomplete?.(), 0);
        };
        transaction.objectStore = () => ({
          get(key) { const request = {}; queueMicrotask(() => { request.result = stores[name].get(key); request.onsuccess?.(); complete(); }); return request; },
          put(value, key) { stores[name].set(key, value); complete(); },
          add(value) { if (stores[name].has(value.intent_id)) throw new Error("Duplicate key"); stores[name].set(value.intent_id, structuredClone(value)); complete(); },
        });
        return transaction;
      },
    };
    return {database, stores};
  }
  const pageInstance = root.crypto?.randomUUID?.();
  async function runPersistentStorage(sources) {
    if (!root.indexedDB) return [{id: "indexedDbReopen", status: "warning", detail: "Browser IndexedDB unavailable; not executed"}];
    const production = compile(sources, ["openEmergencyOfflineDb", "emergencyOfflineRequest", "emergencyOfflineTransaction", "emergencyOfflineEncryptionKey", "storeEncryptedEmergencyIntent", "decryptEmergencyOfflineRecord"], {
      window: {crypto: root.crypto, indexedDB: root.indexedDB},
      EMERGENCY_OFFLINE_DB: "scout-diagnostic-synthetic-offline-v1",
      EMERGENCY_OFFLINE_KEY_ID: "diagnostic_ephemeral_key",
      resolvedPretripProjectId: () => "diagnostic_project_A",
      refreshEmergencyOfflineIntentCount: async () => {},
      fetch: () => { throw new Error("Persistence probe forbids network"); },
    });
    const read = async () => {
      const database = await production.openEmergencyOfflineDb();
      try {
        const transaction = database.transaction("offline_intents", "readonly");
        const record = await production.emergencyOfflineRequest(transaction.objectStore("offline_intents").get("diagnostic.persistence.v2"));
        await production.emergencyOfflineTransaction(transaction);
        if (!record) return null;
        const key = await production.emergencyOfflineEncryptionKey(database);
        requireValue(key.extractable === false, "Persisted CryptoKey became extractable");
        return await production.decryptEmergencyOfflineRecord(database, record);
      } finally { database.close(); }
    };
    const previous = await read();
    if (!previous) await production.storeEncryptedEmergencyIntent({intent_id: "diagnostic.persistence.v2", mission_day_instance_id: "fixture_day", marker: "synthetic-only-v1", pageInstance});
    const restored = await read();
    requireValue(restored?.marker === "synthetic-only-v1", "Real IndexedDB reopen readback differs");
    const acrossPage = Boolean(previous && previous.pageInstance && previous.pageInstance !== pageInstance);
    return [
      {id: "indexedDbReopen", status: "passed", detail: "Real IndexedDB close/reopen, persisted nonextractable CryptoKey and decrypt verified; synthetic database only"},
      {id: "indexedDbAcrossPage", status: acrossPage ? "passed" : "warning", detail: acrossPage ? "Decrypted fixture from a previous page instance" : "Fixture saved. Reopen the page and run again to verify persistence across page instances"},
    ];
  }
  async function runStorage({sources}) {
    requireValue(root.crypto?.subtle, "WebCrypto unavailable: replay not executed");
    const {database, stores} = memoryDatabase();
    let selectedProject = "diagnostic_project_A";
    const state = {emergencyOfflineIntentCount: 0, emergencyOfflineFieldOverlay: {}};
    const names = ["emergencyOfflineEncryptionKey", "storeEncryptedEmergencyIntent", "decryptEmergencyOfflineRecord", "refreshEmergencyOfflineIntentCount"];
    const environment = {
      window: {crypto: root.crypto}, state,
      EMERGENCY_OFFLINE_KEY_ID: "diagnostic_ephemeral_key",
      openEmergencyOfflineDb: async () => database,
      emergencyOfflineRequest: request => new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); }),
      emergencyOfflineTransaction: transaction => new Promise((resolve, reject) => { transaction.oncomplete = resolve; transaction.onerror = () => reject(transaction.error); transaction.onabort = () => reject(new Error("Aborted")); }),
      listEmergencyOfflineRecords: async () => [...stores.offline_intents.values()].map(value => structuredClone(value)),
      resolvedPretripProjectId: () => selectedProject,
      projectId: () => selectedProject,
      asArray: value => Array.isArray(value) ? value : [],
      fetch: () => { throw new Error("Replay forbids network"); },
      localStorage: undefined, indexedDB: undefined, document: undefined,
    };
    const production = compile(sources, names, environment);
    const intent = {intent_id: "diagnostic.fixture.intent", mission_day_instance_id: "fixture_day", decision: "hold", pending_sync: true, device_local_encrypted: true};
    await production.storeEncryptedEmergencyIntent(intent, {intent_type: "field_conflict", group_id: "same_group", row_id: "same_row", category: "field_condition_differs"});
    const record = stores.offline_intents.get(intent.intent_id);
    requireValue(record?.encrypted && record.ciphertext instanceof ArrayBuffer, "Production did not persist encrypted ciphertext");
    requireValue(!new TextDecoder().decode(record.ciphertext).includes(intent.intent_id), "Ciphertext contains plaintext fixture");
    const key = stores.keys.get("diagnostic_ephemeral_key");
    requireValue(key && key.extractable === false, "Encryption key is exportable");
    state.emergencyOfflineFieldOverlay = {};
    const restored = await production.decryptEmergencyOfflineRecord(database, structuredClone(record));
    requireValue(JSON.stringify(restored) === JSON.stringify(intent), "Encrypted readback differs from saved intent");
    let corruptionRejected = false;
    const corrupt = structuredClone(record);
    new Uint8Array(corrupt.ciphertext)[0] ^= 1;
    try { await production.decryptEmergencyOfflineRecord(database, corrupt); } catch { corruptionRejected = true; }
    requireValue(corruptionRejected, "Corrupt ciphertext was accepted");
    let bindingRejected = false;
    try { await production.decryptEmergencyOfflineRecord(database, {...record, intent_id: "different.intent"}); } catch { bindingRejected = true; }
    requireValue(bindingRejected, "Changed intent binding was accepted");
    selectedProject = "diagnostic_project_B";
    await production.refreshEmergencyOfflineIntentCount();
    const crossProjectOverlay = Boolean(state.emergencyOfflineFieldOverlay.same_group);
    selectedProject = "diagnostic_project_A";
    record.created_at = "2000-01-01T00:00:00.000Z";
    state.emergencyOfflineFieldOverlay = {};
    await production.refreshEmergencyOfflineIntentCount();
    const oldPendingOverlay = Boolean(state.emergencyOfflineFieldOverlay.same_group);
    const persistenceChecks = await runPersistentStorage(sources);
    return {
      status: crossProjectOverlay ? "failed" : "warning", evidenceMode: "production_function_replay_memory_idb_real_webcrypto",
      detail: crossProjectOverlay ? "隔離重播發現跨專案 pending overlay；加密讀回與竄改拒絕通過。" : "加密與專案隔離重播通過；持久化結果另列，後端過期拒用未在此頁執行。",
      checks: [...persistenceChecks, {id: "serverExpiryRejection", status: "warning", detail: "Not executed here; requires isolated backend sync tests, not browser inference"}, ...Object.entries({encryptedSaveReadback: true, nonExtractableKey: true, corruptionRejected, intentBindingRejected: bindingRejected, projectOverlayIsolation: !crossProjectOverlay}).map(([id, passed]) => ({id, status: passed ? "passed" : "failed", detail: `${id}: ${passed ? "verified in isolated replay" : "production behavior mismatch"}`}))],
      findings: [ ...(crossProjectOverlay ? ["Cross-project pending field overlay: project A record is shown in project B for the same group identifier."] : []), ...(oldPendingOverlay ? ["Old pending intent still appears as pending overlay. No local expiry contract is established; server expiry/revalidation remains unverified."] : []) ],
      limitations: ["Crypto/isolation replay uses memory; persistence checks use a dedicated synthetic IndexedDB. OS crash durability is not tested.", "No server sync, expiry rejection, runtime approval or outbound delivery was executed."],
      userStorageTouched: false, networkRequests: 0,
    };
  }
  async function runSettings({sources}) {
    const saved = new Map([["scout.dashboardApiBase", "https://previous.invalid"], ["scout.dashboardProjectId", "previous_project"]]);
    const initial = [...saved];
    let failNextProjectWrite = false;
    const fields = {apiBaseInput: {value: "https://diagnostic.invalid/"}, projectInput: {value: "diagnostic_project"}, reloadSettings: {disabled: true}};
    let status;
    const production = compile(sources, ["validateDashboardSettings", "saveDashboardSettings"], {
      document: {getElementById: id => fields[id]}, PROJECT_ID: "fallback_fixture",
      localStorage: {getItem: key => saved.get(key) ?? null, setItem(key, value) { if (failNextProjectWrite && key === "scout.dashboardProjectId") { failNextProjectWrite = false; throw new Error("Fixture quota failure"); } saved.set(key, String(value)); }},
      setDashboardSettingsStatus: (detail, tone, reloadPending) => { status = {detail, tone, reloadPending}; },
      fetch: () => { throw new Error("Replay forbids network"); }, window: undefined,
    });
    try {
      requireValue(production.saveDashboardSettings() === true, "Valid settings save failed");
      const reloadSnapshot = Object.fromEntries(saved);
      requireValue(reloadSnapshot["scout.dashboardApiBase"] === "https://diagnostic.invalid" && reloadSnapshot["scout.dashboardProjectId"] === "diagnostic_project", "Saved values cannot be read back");
      requireValue(fields.reloadSettings.disabled === false && status.reloadPending, "Changed settings did not enable reload");
      requireValue(production.saveDashboardSettings() && fields.reloadSettings.disabled, "Unchanged save still requests reload");
      fields.apiBaseInput.value = "https://diagnostic.invalid?unsafe=1";
      requireValue(production.saveDashboardSettings() === false && status.tone === "bad", "Invalid URL settings were accepted");
      requireValue(JSON.stringify(Object.fromEntries(saved)) === JSON.stringify(reloadSnapshot), "Invalid save changed stored settings");
      fields.apiBaseInput.value = "https://changed.invalid";
      fields.projectInput.value = "changed_project";
      failNextProjectWrite = true;
      requireValue(production.saveDashboardSettings() === false, "Partial storage failure was accepted");
      requireValue(JSON.stringify(Object.fromEntries(saved)) === JSON.stringify(reloadSnapshot), "Partial storage write was not rolled back");
      return {status: "passed", evidenceMode: "production_function_replay_memory_storage", detail: "Settings 正式函式隔離重播：儲存讀回、reload 按鈕、拒絕無效輸入、部分寫入 rollback 通過。", checks: ["saveReadback", "reloadSignal", "unchangedSave", "invalidRejected", "partialWriteRollback"].map(id => ({id, status: "passed", detail: "Verified in isolated memory-storage replay"})), limitations: ["Readback and reload-button signal verified; actual page reload and browser persistence not executed."], userStorageTouched: false, networkRequests: 0};
    } finally { saved.clear(); for (const [key, value] of initial) saved.set(key, value); }
  }
  root.ScoutDiagnosticAdvanced = Object.freeze({runStorage, runSettings});
})(typeof window === "undefined" ? globalThis : window);
