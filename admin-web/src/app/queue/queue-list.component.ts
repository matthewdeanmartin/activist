import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { ApiService } from '../core/api.service';
import { ToastService } from '../core/toast.service';
import { Content, STATUSES } from '../core/models';
import { ProfilePanelComponent } from '../personas/profile-panel.component';
import { ActionBarComponent, Action } from './action-bar.component';

const TABS = ['upcoming', ...STATUSES];

/** Queue + Upcoming list with inline actions (spec/admin_site.md §6.2). */
@Component({
  selector: 'app-queue-list',
  standalone: true,
  imports: [CommonModule, RouterLink, ProfilePanelComponent, ActionBarComponent],
  template: `
    <app-profile-panel></app-profile-panel>

    <nav class="tabs">
      <a
        *ngFor="let t of tabs"
        [routerLink]="['/queue', t]"
        [class.active]="t === status()"
      >
        {{ t.replace('_', ' ') }}
      </a>
    </nav>

    <div class="muted empty" *ngIf="!rows().length">nothing here.</div>

    <div class="rows">
      <div class="row panel" *ngFor="let r of rows()" (click)="open(r)">
        <div class="row-head">
          <span class="badge" [class.post]="!r.is_reply" [class.reply]="r.is_reply">
            {{ r.kind }}
          </span>
          <span class="mono id">{{ r.id }}</span>
          <span [class.over]="r.over_limit" [class.under]="!r.over_limit" class="cc">
            {{ r.char_count }}/500
          </span>
          <span class="badge error" *ngIf="r.error_count">⚑ {{ r.error_count }}</span>
          <span class="badge warn" *ngIf="r.warn_count">⚐ {{ r.warn_count }}</span>
          <span class="muted slot" *ngIf="r.scheduled_for">
            {{ status() === 'upcoming' || status() === 'approved' ? 'slot' : '' }}
            {{ r.scheduled_for }}
            <span class="badge post" *ngIf="isDue(r)">due</span>
          </span>
          <span class="muted engine">{{ r.engine }}</span>
        </div>
        <div class="text">{{ preview(r.text) }}</div>
        <app-action-bar
          [row]="r"
          [liveEditAvailable]="liveEditAvailable()"
          (action)="onAction(r, $event)"
        ></app-action-bar>
      </div>
    </div>
  `,
  styles: [
    `
      .tabs { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 12px; }
      .tabs a {
        text-decoration: none;
        padding: 5px 10px;
        border: 1px solid var(--line);
        border-radius: 6px;
        color: var(--muted);
      }
      .tabs a.active { color: var(--ink); border-color: var(--accent); background: var(--panel-2); }
      .rows { display: grid; gap: 10px; }
      .row { padding: 12px 14px; cursor: pointer; }
      .row:hover { border-color: var(--accent); }
      .row-head { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 12px; }
      .id { color: var(--muted); }
      .text { margin: 8px 0; white-space: pre-wrap; }
      .slot { margin-left: auto; }
      .empty { padding: 20px; }
    `,
  ],
})
export class QueueListComponent implements OnInit {
  readonly tabs = TABS;
  readonly status = signal<string>('pending_review');
  readonly rows = signal<Content[]>([]);
  readonly liveEditAvailable = signal<boolean>(false);

  constructor(
    private api: ApiService,
    private route: ActivatedRoute,
    private router: Router,
    private toast: ToastService,
  ) {}

  ngOnInit() {
    this.api.profile().subscribe((p) => this.liveEditAvailable.set(p.live_edit_available));
    this.route.paramMap.subscribe((params) => {
      this.status.set(params.get('status') ?? 'pending_review');
      this.load();
    });
  }

  load() {
    const s = this.status();
    const obs = s === 'upcoming' ? this.api.upcoming() : this.api.queue(s);
    obs.subscribe({
      next: (rows) => this.rows.set(rows),
      error: (e) => this.toast.fromError(e, 'failed to load queue'),
    });
  }

  open(r: Content) {
    this.router.navigate(['/content', r.id]);
  }

  preview(text: string): string {
    return text.length > 240 ? text.slice(0, 240) + '…' : text;
  }

  isDue(r: Content): boolean {
    return !!r.scheduled_for && r.status === 'approved' && r.scheduled_for <= new Date().toISOString();
  }

  onAction(r: Content, action: Action) {
    const reload = () => this.load();
    const fail = (e: unknown) => {
      this.toast.fromError(e);
      this.load();
    };
    switch (action) {
      case 'approve':
        return this.api.approve(r.id).subscribe({ next: reload, error: fail });
      case 'unapprove':
        return this.api.unapprove(r.id).subscribe({ next: reload, error: fail });
      case 'retry':
        return this.api.retry(r.id).subscribe({ next: reload, error: fail });
      case 'reject': {
        const reason = prompt('Reject reason (optional):') ?? '';
        return this.api.reject(r.id, reason).subscribe({ next: reload, error: fail });
      }
      case 'delete':
        if (!confirm(`Hard-delete ${r.id}? This cannot be undone.`)) return;
        return this.api.remove(r.id).subscribe({ next: reload, error: fail });
      case 'edit-published':
        return this.api.editPublished(r.id, r.text).subscribe({ next: reload, error: fail });
      case 'delete-published':
        return this.api.deletePublished(r.id).subscribe({ next: reload, error: fail });
    }
  }
}
