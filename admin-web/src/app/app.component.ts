import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterOutlet } from '@angular/router';

import { ToastService } from './core/toast.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterOutlet],
  template: `
    <header>
      <h1>activist <span class="muted">admin</span></h1>
      <a class="muted" href="/docs" target="_blank">API docs</a>
    </header>

    <main>
      <router-outlet></router-outlet>
    </main>

    <div class="toasts">
      <div
        *ngFor="let t of toast.toasts()"
        class="toast"
        [class.error]="t.kind === 'error'"
        (click)="toast.dismiss(t.id)"
      >
        {{ t.text }}
      </div>
    </div>
  `,
  styles: [
    `
      header {
        display: flex;
        align-items: baseline;
        gap: 14px;
        padding: 14px 20px;
        border-bottom: 1px solid var(--line);
      }
      h1 { font-size: 18px; margin: 0; }
      main { max-width: 980px; margin: 18px auto; padding: 0 16px; }
      .toasts { position: fixed; right: 16px; bottom: 16px; display: grid; gap: 8px; }
      .toast {
        background: var(--panel-2);
        border: 1px solid var(--accent);
        border-radius: 8px;
        padding: 10px 14px;
        cursor: pointer;
        max-width: 360px;
      }
      .toast.error { border-color: var(--error); }
    `,
  ],
})
export class AppComponent {
  constructor(public toast: ToastService) {}
}
