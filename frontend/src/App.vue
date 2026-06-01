<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  ApiError,
  applyReviewAction,
  fetchReviewItems,
  type ReviewAction,
  type ReviewItem
} from "./api";

const currentReviewer = "alex";
const items = ref<ReviewItem[]>([]);
const selectedId = ref<string | null>(null);
const isLoading = ref(false);
const errorMessage = ref<string | null>(null);
const pendingAction = ref<ReviewAction | null>(null);

const selectedItem = computed(() =>
  items.value.find((item) => item.id === selectedId.value) ?? items.value[0] ?? null
);

const ALL_ACTIONS: ReviewAction[] = ["claim", "approve", "reject", "escalate"];

const ACTION_DISABLED_REASON: Record<ReviewAction, string> = {
  claim: "Only unassigned items can be claimed.",
  approve: "Claim the item before approving.",
  reject: "Claim the item before rejecting.",
  escalate: "Claim the item before escalating."
};

async function loadItems() {
  isLoading.value = true;
  errorMessage.value = null;

  try {
    items.value = await fetchReviewItems();
    selectedId.value = selectedItem.value?.id ?? null;
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "Something went wrong loading the queue.";
  } finally {
    isLoading.value = false;
  }
}

async function performAction(action: ReviewAction) {
  if (!selectedItem.value) return;

  pendingAction.value = action;
  errorMessage.value = null;

  const id = selectedItem.value.id;

  try {
    const updated = await applyReviewAction(id, action, currentReviewer);
    const stillActive = updated.allowed_actions.length > 0;
    if (stillActive) {
      items.value = items.value.map((item) => (item.id === updated.id ? updated : item));
    } else {
      // Terminal item drops out of the active queue.
      items.value = items.value.filter((item) => item.id !== updated.id);
      selectedId.value = items.value[0]?.id ?? null;
    }
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "That action could not be completed.";
  } finally {
    pendingAction.value = null;
  }
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

function isAllowed(item: ReviewItem | null, action: ReviewAction): boolean {
  return Boolean(item && item.allowed_actions.includes(action));
}

function disabledReason(item: ReviewItem | null, action: ReviewAction): string | undefined {
  if (!item) return undefined;
  if (item.allowed_actions.includes(action)) return undefined;
  if (item.allowed_actions.length === 0) {
    return `Item is ${item.status} and cannot accept further actions.`;
  }
  return ACTION_DISABLED_REASON[action];
}

function actionLabel(action: ReviewAction): string {
  return action.charAt(0).toUpperCase() + action.slice(1);
}

function isMine(item: ReviewItem): boolean {
  return item.assigned_reviewer === currentReviewer;
}

onMounted(loadItems);
</script>

<template>
  <main class="page-shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Reviewer workspace</p>
        <h1>Active queue</h1>
      </div>
      <div class="reviewer">Signed in as {{ currentReviewer }}</div>
    </header>

    <p v-if="errorMessage" class="error-banner" role="alert">{{ errorMessage }}</p>
    <p v-if="isLoading" class="loading">Loading review items…</p>

    <section v-else class="workspace">
      <aside class="queue-list" aria-label="Review queue">
        <p v-if="items.length === 0" class="queue-empty">No active items in the queue.</p>
        <button
          v-for="item in items"
          :key="item.id"
          class="queue-item"
          :class="{ selected: item.id === selectedItem?.id, mine: isMine(item) }"
          type="button"
          @click="selectedId = item.id"
        >
          <span class="queue-row">
            <span :class="['risk-pill', `risk-${item.risk_level}`]">{{ item.risk_level }}</span>
            <span v-if="item.customer_tier === 'priority'" class="priority-tag" title="Priority customer">★ Priority</span>
            <span v-if="isMine(item)" class="mine-tag">Mine</span>
          </span>
          <span class="queue-title">{{ item.title }}</span>
          <span class="queue-meta">
            {{ item.status === 'in_review' ? 'In review' : 'Unassigned' }}
            · {{ item.assigned_reviewer ?? "unassigned" }}
          </span>
        </button>
      </aside>

      <section v-if="selectedItem" class="detail-panel">
        <div class="detail-header">
          <div>
            <p class="eyebrow">{{ selectedItem.id }}</p>
            <h2>{{ selectedItem.title }}</h2>
          </div>
          <span :class="['status-pill', `status-${selectedItem.status}`]">{{ selectedItem.status.replace('_', ' ') }}</span>
        </div>

        <dl class="facts">
          <div>
            <dt>Submitted</dt>
            <dd>{{ formatDate(selectedItem.submitted_at) }}</dd>
          </div>
          <div>
            <dt>Risk</dt>
            <dd :class="['risk-pill', `risk-${selectedItem.risk_level}`]">{{ selectedItem.risk_level }}</dd>
          </div>
          <div>
            <dt>Customer</dt>
            <dd>{{ selectedItem.customer_tier }}{{ selectedItem.customer_tier === 'priority' ? ' ★' : '' }}</dd>
          </div>
          <div>
            <dt>Assignee</dt>
            <dd>
              {{ selectedItem.assigned_reviewer ?? "None" }}
              <span v-if="isMine(selectedItem)" class="mine-tag inline">Mine</span>
            </dd>
          </div>
        </dl>

        <p class="summary">{{ selectedItem.summary }}</p>
        <p class="notes">{{ selectedItem.notes_count }} notes on this item</p>

        <div class="actions" aria-label="Workflow actions">
          <button
            v-for="action in ALL_ACTIONS"
            :key="action"
            type="button"
            :disabled="Boolean(pendingAction) || !isAllowed(selectedItem, action)"
            :title="disabledReason(selectedItem, action)"
            :class="{ primary: action === 'claim' && isAllowed(selectedItem, action) }"
            @click="performAction(action)"
          >
            {{ actionLabel(action) }}
          </button>
        </div>
        <p
          v-if="selectedItem && selectedItem.allowed_actions.length === 0"
          class="terminal-note"
        >
          This item is {{ selectedItem.status }}. No further actions are allowed.
        </p>
      </section>
    </section>
  </main>
</template>
