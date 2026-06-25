import { Injectable, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';

export interface Toast {
  id: number;
  text: string;
  kind: 'info' | 'error';
}

/** Non-blocking banners — the JSON equivalent of the Flask UI's flash. */
@Injectable({ providedIn: 'root' })
export class ToastService {
  readonly toasts = signal<Toast[]>([]);
  private seq = 0;

  show(text: string, kind: 'info' | 'error' = 'info') {
    const id = ++this.seq;
    this.toasts.update((t) => [...t, { id, text, kind }]);
    setTimeout(() => this.dismiss(id), 5000);
  }

  /** Map an API error to a human banner, foregrounding the CAS 409 case. */
  fromError(err: unknown, fallback = 'Something went wrong') {
    if (err instanceof HttpErrorResponse) {
      if (err.status === 409) {
        this.show('Another process changed this first — re-fetching.', 'error');
        return;
      }
      if (err.status === 501) {
        this.show(this.detail(err) ?? 'Not available until poster P2.', 'error');
        return;
      }
      this.show(this.detail(err) ?? `${err.status} ${err.statusText}`, 'error');
      return;
    }
    this.show(fallback, 'error');
  }

  private detail(err: HttpErrorResponse): string | null {
    const d = err.error?.detail;
    if (typeof d === 'string') return d;
    if (d && typeof d.detail === 'string') return d.detail;
    return null;
  }

  dismiss(id: number) {
    this.toasts.update((t) => t.filter((x) => x.id !== id));
  }
}
