import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';

import { ApiService } from '../core/api.service';
import { Persona, Profile } from '../core/models';

/** The who / what / how-richly header (spec/admin_site.md §6.1). */
@Component({
  selector: 'app-profile-panel',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="panel profile" *ngIf="profile() as p">
      <div class="who">
        <div class="title">
          {{ p.persona.name }}
          <span class="muted mono">{{ p.persona.handle }}</span>
        </div>
        <div class="muted bio">{{ p.persona.bio }}</div>
        <div class="disclosure muted">{{ p.persona.disclosure }}</div>
      </div>

      <div class="what">
        <div>
          <span class="muted">account</span>
          <span class="mono">{{ accountLabel(p) }}</span>
          <span class="badge" [class.error]="!p.account.base_url">
            {{ p.account.verified ? 'verified' : p.account.base_url ? 'configured' : 'no creds' }}
          </span>
        </div>
        <div>
          <span class="muted">engine</span>
          <span class="badge post">{{ engineLabel(p) }}</span>
          <span class="badge">mod: {{ p.engine.moderation_engine }}</span>
        </div>
        <div>
          <span class="muted">publishing</span>
          <span class="badge" [class.error]="p.engine.poster_live" [class.under]="!p.engine.poster_live">
            {{ p.engine.poster_live ? 'LIVE' : 'dry-run' }}
          </span>
          <span class="badge">vis: {{ p.engine.default_visibility }}</span>
          <span class="badge warn" *ngIf="!p.live_edit_available" title="lands with poster P2">
            posted edit/delete: P2
          </span>
        </div>
      </div>

      <div class="counts">
        <span class="badge" *ngFor="let c of countList(p)">
          {{ c.k }}: <b>{{ c.v }}</b>
        </span>
        <span class="muted last-fetch" *ngIf="p.last_fetch">
          last fetch {{ p.last_fetch.ts }}
        </span>
      </div>

      <div class="personas muted" *ngIf="personas().length > 1">
        personas:
        <span *ngFor="let pe of personas()" class="badge" [class.post]="pe.active">
          {{ pe.persona_id }}{{ pe.active ? ' ●' : '' }}
        </span>
      </div>
    </div>
  `,
  styles: [
    `
      .profile { padding: 14px 16px; display: grid; gap: 10px; margin-bottom: 14px; }
      .title { font-size: 18px; font-weight: 600; }
      .what > div { margin: 2px 0; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
      .what .muted { min-width: 84px; display: inline-block; }
      .counts { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
      .last-fetch { margin-left: auto; }
      .disclosure { font-size: 12px; }
    `,
  ],
})
export class ProfilePanelComponent implements OnInit {
  readonly profile = signal<Profile | null>(null);
  readonly personas = signal<Persona[]>([]);

  constructor(private api: ApiService) {}

  ngOnInit() {
    this.api.profile().subscribe((p) => this.profile.set(p));
    this.api.personas().subscribe((ps) => this.personas.set(ps));
  }

  accountLabel(p: Profile): string {
    if (p.account.handle) return '@' + p.account.handle;
    return p.account.mastodon_id;
  }

  engineLabel(p: Profile): string {
    return p.engine.model ? `${p.engine.engine}:${p.engine.model}` : p.engine.engine;
  }

  countList(p: Profile): { k: string; v: number }[] {
    return Object.entries(p.counts)
      .filter(([, v]) => v > 0)
      .map(([k, v]) => ({ k: k.replace('_', ' '), v }));
  }
}
