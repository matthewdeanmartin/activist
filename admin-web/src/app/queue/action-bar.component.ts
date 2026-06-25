import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

import { Content } from '../core/models';

export type Action =
  | 'approve'
  | 'reject'
  | 'unapprove'
  | 'retry'
  | 'delete'
  | 'edit-published'
  | 'delete-published';

/**
 * The status-aware button row (spec/admin_site.md §6). Renders only the buttons
 * legal for the row's status; the server re-validates every one via CAS.
 */
@Component({
  selector: 'app-action-bar',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="actions">
      <button
        *ngIf="row.status === 'pending_review'"
        class="primary"
        (click)="emit('approve', $event)"
      >
        approve
      </button>
      <button *ngIf="row.status === 'pending_review'" (click)="emit('reject', $event)">
        reject
      </button>
      <button *ngIf="row.status === 'approved'" (click)="emit('unapprove', $event)">
        unapprove
      </button>
      <button *ngIf="row.status === 'failed'" (click)="emit('retry', $event)">retry</button>

      <button
        *ngIf="deletable()"
        class="danger"
        (click)="emit('delete', $event)"
        title="hard-remove this queue row"
      >
        delete
      </button>

      <!-- already-posted: live edit/delete, disabled until poster P2 -->
      <ng-container *ngIf="row.status === 'published'">
        <button
          [disabled]="!liveEditAvailable"
          [title]="liveEditAvailable ? 'edit the live status' : 'lands with poster P2'"
          (click)="emit('edit-published', $event)"
        >
          edit posted
        </button>
        <button
          class="danger"
          [disabled]="!liveEditAvailable"
          [title]="liveEditAvailable ? 'delete the live status' : 'lands with poster P2'"
          (click)="emit('delete-published', $event)"
        >
          delete posted
        </button>
      </ng-container>
    </div>
  `,
  styles: [`.actions { display: flex; gap: 6px; flex-wrap: wrap; }`],
})
export class ActionBarComponent {
  @Input({ required: true }) row!: Content;
  @Input() liveEditAvailable = false;
  @Output() action = new EventEmitter<Action>();

  deletable(): boolean {
    return ['pending_review', 'approved', 'failed', 'rejected'].includes(this.row.status);
  }

  emit(a: Action, ev: Event) {
    ev.stopPropagation();
    this.action.emit(a);
  }
}
