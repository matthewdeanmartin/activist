import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { ApiService } from '../core/api.service';
import { ToastService } from '../core/toast.service';
import { Content, Event } from '../core/models';
import { ActionBarComponent, Action } from './action-bar.component';

/** Full content view: text, flags, opinion change, reply context, edit, events. */
@Component({
  selector: 'app-content-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ActionBarComponent],
  template: `
    <a routerLink="/" class="back">← queue</a>

    <ng-container *ngIf="row() as r">
      <div class="panel head">
        <span class="badge" [class.post]="!r.is_reply" [class.reply]="r.is_reply">{{ r.kind }}</span>
        <span class="badge">{{ r.status.replace('_', ' ') }}</span>
        <span class="mono muted">{{ r.id }}</span>
        <span class="muted">{{ r.identity }}</span>
        <span *ngIf="r.scheduled_for" class="muted">slot {{ r.scheduled_for }}</span>
        <span *ngIf="r.visibility && r.visibility !== 'public'" class="badge warn">
          {{ r.visibility }}
        </span>
        <a *ngIf="r.published_url" [href]="r.published_url" target="_blank">live ↗</a>
      </div>

      <!-- reply context -->
      <div class="panel reply-ctx" *ngIf="r.is_reply && r.reply_to_text">
        <div class="muted">↩ replying to {{ r.reply_to_author }}</div>
        <div class="quoted">{{ r.reply_to_text }}</div>
      </div>

      <!-- moderation flags -->
      <div class="panel flags" *ngIf="r.flags.length">
        <div *ngFor="let f of r.flags" class="flag" [class.error]="f.severity === 'error'">
          <span class="badge" [class.error]="f.severity === 'error'" [class.warn]="f.severity === 'warn'">
            {{ f.severity }}
          </span>
          <span class="mono">{{ f.policy }}/{{ f.rule }}</span>
          <span class="muted">{{ f.detail }}</span>
        </div>
      </div>

      <!-- opinion change -->
      <div class="panel opinion" *ngIf="r.opinion_change as oc">
        <b>opinion change</b> [{{ oc.key }}]:
        <span class="muted">{{ oc.old_stance }}</span> ▸
        <span>{{ oc.new_stance }}</span>
        <div class="muted reason">{{ oc.reason }}</div>
      </div>

      <!-- editor -->
      <div class="panel editor" *ngIf="editable(r); else readonlyText">
        <textarea [(ngModel)]="draft" rows="6"></textarea>
        <div class="editor-meta">
          <span [class.over]="draft.length > 500" [class.under]="draft.length <= 500">
            {{ draft.length }}/500
          </span>
          <div class="spacer"></div>
          <button (click)="save(r)" [disabled]="!draft.trim() || busy()">save edit</button>
          <button
            class="primary"
            *ngIf="r.status === 'pending_review'"
            (click)="editApprove(r)"
            [disabled]="!draft.trim() || busy()"
          >
            edit &amp; approve
          </button>
          <button (click)="recheck(r)" [disabled]="busy()" title="re-run LLM moderation (costs $)">
            recheck (LLM)
          </button>
        </div>
      </div>
      <ng-template #readonlyText>
        <div class="panel text">{{ r.text }}</div>
      </ng-template>

      <div *ngIf="r.rejected_reason" class="panel rejected">
        <b>rejected:</b> {{ r.rejected_reason }}
      </div>

      <app-action-bar
        [row]="r"
        [liveEditAvailable]="liveEditAvailable()"
        (action)="onAction(r, $event)"
      ></app-action-bar>

      <!-- source -->
      <div class="muted source" *ngIf="r.source_url">
        source: <a [href]="r.source_url" target="_blank">{{ r.source_title || r.source_url }}</a>
      </div>

      <!-- event log -->
      <div class="panel events">
        <b>history</b>
        <table>
          <tr *ngFor="let e of events()">
            <td class="mono muted">{{ e.ts }}</td>
            <td>{{ e.actor }}</td>
            <td><b>{{ e.action }}</b></td>
            <td class="muted">{{ e.detail }}</td>
          </tr>
        </table>
      </div>
    </ng-container>
  `,
  styles: [
    `
      .back { display: inline-block; margin-bottom: 12px; }
      .panel { padding: 12px 14px; margin-bottom: 12px; }
      .head { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
      .text, .quoted { white-space: pre-wrap; }
      .quoted { border-left: 3px solid var(--reply); padding-left: 10px; margin-top: 6px; }
      .flag { display: flex; gap: 8px; align-items: center; padding: 2px 0; }
      .editor-meta { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
      .spacer { flex: 1; }
      .opinion .reason { margin-top: 4px; }
      .events table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 6px; }
      .events td { padding: 2px 8px 2px 0; vertical-align: top; }
      .rejected { border-color: var(--error); }
      .source { margin-bottom: 12px; }
    `,
  ],
})
export class ContentDetailComponent implements OnInit {
  readonly row = signal<Content | null>(null);
  readonly events = signal<Event[]>([]);
  readonly liveEditAvailable = signal<boolean>(false);
  readonly busy = signal<boolean>(false);
  draft = '';

  constructor(
    private api: ApiService,
    private route: ActivatedRoute,
    private router: Router,
    private toast: ToastService,
  ) {}

  ngOnInit() {
    this.api.profile().subscribe((p) => this.liveEditAvailable.set(p.live_edit_available));
    this.route.paramMap.subscribe((params) => this.load(params.get('id')!));
  }

  load(id: string) {
    this.api.content(id).subscribe({
      next: (d) => {
        this.row.set(d.content);
        this.events.set(d.events);
        this.draft = d.content.text;
      },
      error: (e) => this.toast.fromError(e, 'content not found'),
    });
  }

  editable(r: Content): boolean {
    return r.status === 'pending_review' || r.status === 'approved';
  }

  private run<T>(obs: { subscribe: Function }, ok = 'done') {
    this.busy.set(true);
    (obs as any).subscribe({
      next: () => {
        this.busy.set(false);
        this.toast.show(ok);
        this.load(this.row()!.id);
      },
      error: (e: unknown) => {
        this.busy.set(false);
        this.toast.fromError(e);
        this.load(this.row()!.id);
      },
    });
  }

  save(r: Content) {
    this.run(this.api.edit(r.id, this.draft.trim()), 'saved');
  }

  editApprove(r: Content) {
    this.run(this.api.editApprove(r.id, this.draft.trim()), 'edited & approved');
  }

  recheck(r: Content) {
    this.run(this.api.recheckLlm(r.id), 'rechecked');
  }

  onAction(r: Content, action: Action) {
    switch (action) {
      case 'approve':
        return this.run(this.api.approve(r.id), 'approved');
      case 'unapprove':
        return this.run(this.api.unapprove(r.id), 'put back in queue');
      case 'retry':
        return this.run(this.api.retry(r.id), 'retrying');
      case 'reject': {
        const reason = prompt('Reject reason (optional):') ?? '';
        return this.run(this.api.reject(r.id, reason), 'rejected');
      }
      case 'delete':
        if (!confirm(`Hard-delete ${r.id}? This cannot be undone.`)) return;
        this.busy.set(true);
        return this.api.remove(r.id).subscribe({
          next: () => this.router.navigate(['/']),
          error: (e) => {
            this.busy.set(false);
            this.toast.fromError(e);
          },
        });
      case 'edit-published':
        return this.run(this.api.editPublished(r.id, this.draft.trim()), 'edited live status');
      case 'delete-published':
        return this.run(this.api.deletePublished(r.id), 'deleted live status');
    }
  }
}
