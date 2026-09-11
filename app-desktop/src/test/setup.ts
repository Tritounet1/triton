// Auto-registers jest-dom's matchers (toBeInTheDocument, toHaveClass,
// toHaveTextContent...) on Vitest's expect - loaded once for every test
// file via vitest.config.ts's setupFiles, so individual test files don't
// each need this import.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom unmounts nothing between tests on its own (no "globals: true" in
// vitest.config.ts, so Testing Library's own auto-cleanup - which only
// registers itself when it detects a global afterEach - never kicks in):
// without this, a component rendered by one test stays in the document for
// the next one, so `screen` queries can match stale elements or throw on
// duplicates.
afterEach(() => {
  cleanup();
});

// jsdom does not implement <dialog>.showModal()/close() at runtime (see
// https://github.com/jsdom/jsdom/issues/3294), even though @types/node's DOM
// lib declares them as always present - components built on the native
// <dialog> element (this project's Dialog/AlertDialog) call these in an
// effect as soon as `isOpen` becomes true, which throws in jsdom and breaks
// any test that opens one. The polyfill only needs to reflect the "open"
// attribute; the actual open/closed state rendered in tests comes from the
// component's own `isOpen` prop, not from this attribute.
/* eslint-disable @typescript-eslint/no-unnecessary-condition --
   the lint rule trusts the DOM lib types (always defined), but jsdom's
   actual runtime object does not define these methods. */
if (typeof HTMLDialogElement !== "undefined" && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
}
/* eslint-enable @typescript-eslint/no-unnecessary-condition */
