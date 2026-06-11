<template>
  <Teleport to="body">
    <div
      v-if="modelValue"
      class="fixed inset-0 flex items-end justify-center overflow-y-auto p-2 sm:items-center sm:p-4"
      :style="{ zIndex: resolvedZIndex }"
      role="dialog"
      aria-modal="true"
    >
      <div
        class="absolute inset-0 bg-black/50"
        aria-hidden="true"
        @click="$emit('update:modelValue', false)"
      />
      <slot />
    </div>
  </Teleport>
</template>

<script>
const DEFAULT_DIALOG_Z_INDEX = 2000;
let bodyScrollLockCount = 0;
let savedBodyStyle = null;
let savedScrollY = 0;
let dialogIdSeq = 0;
const openDialogIds = [];
const stackListeners = new Set();

function notifyStackListeners() {
  for (const listener of stackListeners) listener();
}
</script>

<script setup>
import { onUnmounted, ref, watch } from "vue";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  zIndex: { type: Number, default: DEFAULT_DIALOG_Z_INDEX },
});

const emit = defineEmits(["update:modelValue"]);
const dialogId = ++dialogIdSeq;
const resolvedZIndex = ref(props.zIndex);
let isDialogOpen = false;

function isTopDialog() {
  return openDialogIds[openDialogIds.length - 1] === dialogId;
}

function syncZIndex() {
  const stackIndex = openDialogIds.indexOf(dialogId);
  resolvedZIndex.value = props.zIndex + Math.max(stackIndex, 0) * 10;
}

function registerDialog() {
  if (!openDialogIds.includes(dialogId)) {
    openDialogIds.push(dialogId);
    notifyStackListeners();
  }
}

function unregisterDialog() {
  const index = openDialogIds.indexOf(dialogId);
  if (index !== -1) {
    openDialogIds.splice(index, 1);
    notifyStackListeners();
  }
}

function onKeydown(e) {
  if (e.key ==="Escape" && props.modelValue && isTopDialog()) {
    emit("update:modelValue", false);
  }
}

function lockBodyScroll() {
  if (typeof document ==="undefined") return;
  if (bodyScrollLockCount === 0) {
    savedScrollY = window.scrollY || document.documentElement.scrollTop || 0;
    savedBodyStyle = {
      overflow: document.body.style.overflow,
      paddingRight: document.body.style.paddingRight,
      position: document.body.style.position,
      top: document.body.style.top,
      left: document.body.style.left,
      right: document.body.style.right,
      width: document.body.style.width,
    };
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow ="hidden";
    document.body.style.position ="fixed";
    document.body.style.top = `-${savedScrollY}px`;
    document.body.style.left ="0";
    document.body.style.right ="0";
    document.body.style.width ="100%";
    if (scrollbarWidth > 0) {
      document.body.style.paddingRight = `${scrollbarWidth}px`;
    }
  }
  bodyScrollLockCount += 1;
}

function unlockBodyScroll() {
  if (typeof document ==="undefined") return;
  bodyScrollLockCount = Math.max(0, bodyScrollLockCount - 1);
  if (bodyScrollLockCount === 0) {
    const restoreScrollY = savedScrollY;
    if (savedBodyStyle) {
      document.body.style.overflow = savedBodyStyle.overflow;
      document.body.style.paddingRight = savedBodyStyle.paddingRight;
      document.body.style.position = savedBodyStyle.position;
      document.body.style.top = savedBodyStyle.top;
      document.body.style.left = savedBodyStyle.left;
      document.body.style.right = savedBodyStyle.right;
      document.body.style.width = savedBodyStyle.width;
      savedBodyStyle = null;
    }
    savedScrollY = 0;
    requestAnimationFrame(() => window.scrollTo(0, restoreScrollY));
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open && !isDialogOpen) {
      isDialogOpen = true;
      registerDialog();
      lockBodyScroll();
      window.addEventListener("keydown", onKeydown);
    } else if (!open && isDialogOpen) {
      isDialogOpen = false;
      unregisterDialog();
      unlockBodyScroll();
      window.removeEventListener("keydown", onKeydown);
    }
  },
  { immediate: true }
);

stackListeners.add(syncZIndex);
syncZIndex();
watch(() => props.zIndex, syncZIndex);

onUnmounted(() => {
  if (isDialogOpen) {
    unregisterDialog();
    unlockBodyScroll();
  }
  stackListeners.delete(syncZIndex);
  window.removeEventListener("keydown", onKeydown);
});
</script>
