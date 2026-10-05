// Node 25+ defines its own global localStorage/sessionStorage (undefined unless
// started with --localstorage-file). Vitest copies jsdom's window onto the
// global only for names Node does not already have, so on newer Node the tests
// would see Node's empty storage instead of jsdom's. Put jsdom's back.
if (globalThis.jsdom) {
  for (const name of ['localStorage', 'sessionStorage']) {
    Object.defineProperty(globalThis, name, {
      value: globalThis.jsdom.window[name], configurable: true, writable: true,
    })
  }
}
