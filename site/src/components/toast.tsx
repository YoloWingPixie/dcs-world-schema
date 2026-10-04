"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type ToastMessage = { id: number; text: string; href?: string; linkText?: string };
const EVENT = "dcs-ref:toast";
let seq = 0;

export function showToast(text: string, href?: string, linkText?: string) {
  const detail: ToastMessage = { id: ++seq, text };
  if (href) detail.href = href;
  if (linkText) detail.linkText = linkText;
  window.dispatchEvent(new CustomEvent<ToastMessage>(EVENT, { detail }));
}

export function Toaster() {
  const [toast, setToast] = useState<ToastMessage | null>(null);
  useEffect(() => {
    const onToast = (event: Event) => setToast((event as CustomEvent<ToastMessage>).detail);
    window.addEventListener(EVENT, onToast);
    return () => window.removeEventListener(EVENT, onToast);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 4500);
    return () => window.clearTimeout(timer);
  }, [toast]);
  return (
    <div aria-live="polite">
      {toast ? (
        <div className="toast" key={toast.id}>
          <span>{toast.text}</span>
          {toast.href ? <Link href={toast.href}>{toast.linkText ?? "Open"}</Link> : null}
        </div>
      ) : null}
    </div>
  );
}
