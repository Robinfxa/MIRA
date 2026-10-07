import {mountMemoryManagement} from '../features/session/memory-management.js';
import type {MemoryManagementApp} from '../features/session/memory-management.js';
import {mountOperatorPairing} from '../features/session/operator-pairing.js';

let memoryManagement: MemoryManagementApp | null = null;

mountOperatorPairing(document, {
  localOnly: true,
  onPaired() {
    memoryManagement = mountMemoryManagement(document, {localOnly: true});
    return {
      async stopAndClose() {
        memoryManagement?.close();
        memoryManagement = null;
      },
    };
  },
});
