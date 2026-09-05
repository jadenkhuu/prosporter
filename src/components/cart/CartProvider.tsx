"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";

export type CartLine = {
  key: string; // slug + size
  slug: string;
  name: string;
  price: number;
  image: string;
  size: string | null;
  qty: number;
};

type AddPayload = Omit<CartLine, "key" | "qty"> & { qty?: number };

type Action =
  | { type: "add"; line: AddPayload }
  | { type: "remove"; key: string }
  | { type: "setQty"; key: string; qty: number }
  | { type: "clear" }
  | { type: "hydrate"; lines: CartLine[] };

const keyFor = (slug: string, size: string | null) => `${slug}__${size ?? "os"}`;

function reducer(state: CartLine[], action: Action): CartLine[] {
  switch (action.type) {
    case "hydrate":
      return action.lines;
    case "add": {
      const key = keyFor(action.line.slug, action.line.size);
      const existing = state.find((l) => l.key === key);
      const qty = action.line.qty ?? 1;
      if (existing) {
        return state.map((l) => (l.key === key ? { ...l, qty: l.qty + qty } : l));
      }
      return [...state, { ...action.line, key, qty }];
    }
    case "remove":
      return state.filter((l) => l.key !== action.key);
    case "setQty":
      return state
        .map((l) => (l.key === action.key ? { ...l, qty: Math.max(0, action.qty) } : l))
        .filter((l) => l.qty > 0);
    case "clear":
      return [];
    default:
      return state;
  }
}

type CartContext = {
  lines: CartLine[];
  count: number;
  subtotal: number;
  isOpen: boolean;
  open: () => void;
  close: () => void;
  add: (line: AddPayload) => void;
  remove: (key: string) => void;
  setQty: (key: string, qty: number) => void;
  clear: () => void;
};

const Ctx = createContext<CartContext | null>(null);
const STORAGE_KEY = "prosporter.cart.v1";

export function CartProvider({ children }: { children: React.ReactNode }) {
  const [lines, dispatch] = useReducer(reducer, []);
  const [isOpen, setOpen] = useState(false);
  // Effects run in order on mount: hydrate first, then persist. The persist
  // effect must skip that first run or it would overwrite the stored cart with
  // the empty initial state before the hydrate dispatch has re-rendered.
  const hydrated = useRef(false);

  // Load persisted cart once on mount.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) dispatch({ type: "hydrate", lines: JSON.parse(raw) });
    } catch {
      /* ignore malformed storage */
    }
  }, []);

  // Persist on change (after initial hydration).
  useEffect(() => {
    if (!hydrated.current) {
      hydrated.current = true;
      return;
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(lines));
  }, [lines]);

  const value = useMemo<CartContext>(() => {
    const count = lines.reduce((n, l) => n + l.qty, 0);
    const subtotal = lines.reduce((n, l) => n + l.qty * l.price, 0);
    return {
      lines,
      count,
      subtotal,
      isOpen,
      open: () => setOpen(true),
      close: () => setOpen(false),
      add: (line) => {
        dispatch({ type: "add", line });
        setOpen(true);
      },
      remove: (key) => dispatch({ type: "remove", key }),
      setQty: (key, qty) => dispatch({ type: "setQty", key, qty }),
      clear: () => dispatch({ type: "clear" }),
    };
  }, [lines, isOpen]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCart() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useCart must be used within CartProvider");
  return ctx;
}
