import { Routes } from '@angular/router';

import { QueueListComponent } from './queue/queue-list.component';
import { ContentDetailComponent } from './queue/content-detail.component';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'queue/pending_review' },
  { path: 'queue/:status', component: QueueListComponent },
  { path: 'content/:id', component: ContentDetailComponent },
  { path: '**', redirectTo: 'queue/pending_review' },
];
