// src/store/createSelectors.ts
import type { StoreApi } from "zustand";

type ZustandHook<T> = {
  <U>(selector: (state: T) => U): U;
  (): T;
} & StoreApi<T>;

export function createSelectors<T extends object>(
  useStore: ZustandHook<T>
): ZustandHook<T> & {
  use: {
    [K in keyof T]: () => T[K];
  };
} {
  const proxy = new Proxy(
    {},
    {
      get: (_, key: string) => {
        return () => useStore((state) => state[key as keyof T]);
      },
    }
  );

  // 👇 Add correct typing to proxy object
  (useStore as ZustandHook<T> & { use: any }).use = proxy as {
    [K in keyof T]: () => T[K];
  };

  return useStore as ZustandHook<T> & {
    use: {
      [K in keyof T]: () => T[K];
    };
  };
}
