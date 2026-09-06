import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// @testing-library/react's automatic cleanup registers on the GLOBAL afterEach,
// which doesn't exist with `globals: false`. Register it explicitly.
afterEach(() => {
  cleanup();
});
