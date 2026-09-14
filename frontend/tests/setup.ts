import '@testing-library/jest-dom/vitest';
import {afterEach,beforeEach,vi} from 'vitest';
import {cleanup} from '@testing-library/react';
// jsdom has no layout/scroll implementation. The real mobile viewport assertion
// is in Playwright; component tests assert the requested scroll destination.
beforeEach(()=>{HTMLElement.prototype.scrollIntoView=vi.fn();});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();localStorage.clear();sessionStorage.clear();history.replaceState(null,'','/');});
