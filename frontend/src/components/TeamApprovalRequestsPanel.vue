<template>
  <div class="min-w-0">
    <PageToolbar title="团队申请" icon="inbox">
      <template #actions>
        <NativeSelect v-model="filters.status" class="w-full sm:w-36" @change="loadRequests">
          <option value="">全部状态</option>
          <option value="pending">待审核</option>
          <option value="running">执行中</option>
          <option value="completed">已完成</option>
          <option value="failed">失败</option>
          <option value="rejected">已驳回</option>
        </NativeSelect>
        <NativeSelect v-model="filters.request_type" class="w-full sm:w-40" @change="loadRequests">
          <option value="">全部类型</option>
          <option value="image_tag">镜像打标</option>
          <option value="image_migration">镜像迁移</option>
        </NativeSelect>
        <Button variant="outline" size="sm" class="w-full min-h-11 sm:w-auto" :disabled="loading" @click="loadRequests">
          <AppIcon name="sync-alt" />
          刷新
        </Button>
      </template>
    </PageToolbar>

    <div v-if="loading && !requests.length" class="flex justify-center py-12 text-slate-500">
      <AppIcon name="spinner" class="mr-2" spin /> 加载中...
    </div>

    <EmptyState v-else-if="!requests.length" message="暂无团队申请" icon="inbox" />

    <div v-else class="overflow-x-auto rounded-lg border border-slate-200">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>申请</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>申请人</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>审批人</TableHead>
            <TableHead>时间</TableHead>
            <TableHead class="text-end">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="item in requests" :key="item.request_id">
            <TableCell>
              <div class="max-w-md">
                <div class="font-medium text-slate-900">{{ item.title || "-" }}</div>
                <div v-if="isImageRequest(item)" class="mt-1 text-xs text-slate-500">
                  <code>{{ imageRequestSummary(item) }}</code>
                </div>
              </div>
            </TableCell>
            <TableCell>{{ requestTypeLabel(item.request_type) }}</TableCell>
            <TableCell>{{ userLabel(item.requested_by_username, item.requested_by) }}</TableCell>
            <TableCell>
              <Badge :variant="statusVariant(item.status)">{{ statusLabel(item.status) }}</Badge>
              <div v-if="item.error" class="mt-1 max-w-xs truncate text-xs text-red-600" :title="item.error">
                {{ item.error }}
              </div>
            </TableCell>
            <TableCell>{{ userLabel(item.reviewed_by_username, item.reviewed_by) }}</TableCell>
            <TableCell class="text-sm text-slate-500">
              <div>{{ formatTime(item.created_at) }}</div>
              <div v-if="item.reviewed_at" class="text-xs">审核 {{ formatTime(item.reviewed_at) }}</div>
            </TableCell>
            <TableCell class="text-end">
              <div class="flex flex-wrap justify-end gap-1">
                <Button size="sm" variant="outline" title="查看" @click="openDetail(item)">
                  <AppIcon name="eye" />
                </Button>
                <Button v-if="canReview && item.status === 'pending'" size="sm" variant="outline" title="同意" @click="approveRequest(item)">
                  <AppIcon name="play" />
                </Button>
                <Button v-if="canReview && item.status === 'pending'" size="sm" variant="destructive" title="驳回" @click="openRejectDialog(item)">
                  <AppIcon name="times" />
                </Button>
              </div>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>

    <FormDialog v-model="showDetail" title="申请详情" icon="inbox" size="lg">
      <div v-if="selected" class="space-y-4 text-sm">
        <div class="grid gap-3 sm:grid-cols-2">
          <div>
            <div class="text-xs text-slate-500">类型</div>
            <div class="font-medium">{{ requestTypeLabel(selected.request_type) }}</div>
          </div>
          <div>
            <div class="text-xs text-slate-500">状态</div>
            <Badge :variant="statusVariant(selected.status)">{{ statusLabel(selected.status) }}</Badge>
          </div>
          <div>
            <div class="text-xs text-slate-500">申请人</div>
            <div>{{ userLabel(selected.requested_by_username, selected.requested_by) }}</div>
          </div>
          <div>
            <div class="text-xs text-slate-500">审核人</div>
            <div>{{ userLabel(selected.reviewed_by_username, selected.reviewed_by) }}</div>
          </div>
        </div>

        <div v-if="isImageRequest(selected)" class="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <dl class="grid gap-2 sm:grid-cols-[7rem_1fr]">
            <dt class="text-slate-500">源仓库</dt>
            <dd>{{ sourceRegistryFor(selected.payload) }}</dd>
            <dt class="text-slate-500">源镜像</dt>
            <dd><code>{{ sourceImageFor(selected) }}</code></dd>
            <dt class="text-slate-500">目标仓库</dt>
            <dd>{{ targetRegistryFor(selected.payload) }}</dd>
            <dt class="text-slate-500">目标镜像</dt>
            <dd><code>{{ targetImageFor(selected) }}</code></dd>
            <dt class="text-slate-500">允许覆盖</dt>
            <dd>{{ selected.payload?.allow_overwrite ? "是" : "否" }}</dd>
            <dt v-if="selected.result?.migration_task_id" class="text-slate-500">迁移任务</dt>
            <dd v-if="selected.result?.migration_task_id">
              <code>{{ selected.result.migration_task_id }}</code>
            </dd>
          </dl>
        </div>

        <div v-else>
          <div class="mb-1 text-xs text-slate-500">Payload</div>
          <pre class="max-h-80 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">{{ prettyJson(selected.payload) }}</pre>
        </div>

        <AlertBanner
          v-if="selected.payload?.allow_overwrite && isImageRequest(selected)"
          message="目标标签可能被覆盖，请确认这是预期操作。"
          variant="warning"
        />
        <AlertBanner v-if="selected.review_note" :message="`审核备注：${selected.review_note}`" />
        <AlertBanner v-if="selected.error" :message="selected.error" variant="danger" />
      </div>
      <template #footer>
        <Button variant="outline" class="w-full sm:w-auto" @click="showDetail = false">关闭</Button>
      </template>
    </FormDialog>

    <FormDialog v-model="showReject" title="驳回申请" icon="times" size="md">
      <div class="space-y-2">
        <Label>驳回原因</Label>
        <Input v-model="rejectNote" placeholder="请输入驳回原因" />
      </div>
      <template #footer>
        <Button variant="outline" class="w-full sm:w-auto" @click="showReject = false">取消</Button>
        <Button variant="destructive" class="w-full sm:w-auto" :disabled="rejecting" @click="rejectRequest">
          <AppIcon v-if="rejecting" name="spinner" spin />
          驳回
        </Button>
      </template>
    </FormDialog>
  </div>
</template>

<script setup>
import axios from "axios";
import { computed, onMounted, ref } from "vue";
import { toastApiError, toastSuccess } from "@/utils/notify";
import { showConfirm } from "@/composables/useConfirm";
import { useTeamStore } from "@/stores/team";
import PageToolbar from "@/components/ui/PageToolbar.vue";
import EmptyState from "@/components/ui/EmptyState.vue";
import AlertBanner from "@/components/ui/AlertBanner.vue";
import Button from "@/components/ui/button/Button.vue";
import Badge from "@/components/ui/badge/Badge.vue";
import Input from "@/components/ui/input/Input.vue";
import Label from "@/components/ui/label/Label.vue";
import NativeSelect from "@/components/ui/select/NativeSelect.vue";
import FormDialog from "@/components/ui/dialog/FormDialog.vue";
import Table from "@/components/ui/table/Table.vue";
import TableHeader from "@/components/ui/table/TableHeader.vue";
import TableBody from "@/components/ui/table/TableBody.vue";
import TableRow from "@/components/ui/table/TableRow.vue";
import TableHead from "@/components/ui/table/TableHead.vue";
import TableCell from "@/components/ui/table/TableCell.vue";

const teamStore = useTeamStore();
const requests = ref([]);
const loading = ref(false);
const selected = ref(null);
const showDetail = ref(false);
const showReject = ref(false);
const rejecting = ref(false);
const rejectNote = ref("");
const rejectTarget = ref(null);
const filters = ref({ status: "", request_type: "" });

const canReview = computed(() => teamStore.canManageTeam);

function params() {
  const out = {};
  if (filters.value.status) out.status = filters.value.status;
  if (filters.value.request_type) out.request_type = filters.value.request_type;
  return out;
}

async function loadRequests() {
  loading.value = true;
  try {
    const res = await axios.get("/api/team-approval-requests", { params: params() });
    requests.value = res.data?.requests || [];
  } catch (e) {
    toastApiError(e, "加载团队申请失败");
  } finally {
    loading.value = false;
  }
}

function isImageRequest(item) {
  return ["image_tag", "image_migration"].includes(item?.request_type);
}

function requestTypeLabel(type) {
  if (type === "image_tag") return "镜像打标";
  if (type === "image_migration") return "镜像迁移";
  return type || "未知类型";
}

function statusLabel(status) {
  return {
    pending: "待审核",
    approved: "已同意",
    running: "执行中",
    completed: "已完成",
    failed: "失败",
    rejected: "已驳回",
    canceled: "已取消",
  }[status] || status || "-";
}

function statusVariant(status) {
  if (status === "completed") return "success";
  if (status === "failed" || status === "rejected") return "danger";
  if (status === "running" || status === "approved") return "info";
  if (status === "pending") return "warning";
  return "default";
}

function userLabel(username, userId) {
  return username || userId || "-";
}

function formatTime(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

function sourceRegistryFor(payload = {}) {
  return payload.source_registry_name || payload.registry_name || "-";
}

function targetRegistryFor(payload = {}) {
  return payload.target_registry_name || payload.registry_name || "-";
}

function sourceImageFor(item = {}) {
  const payload = item.payload || item || {};
  const result = item.result || {};
  return result.source_image || payload.source_image || `${payload.image_name || "-"}:${payload.source_tag || "latest"}`;
}

function targetImageFor(item = {}) {
  const payload = item.payload || item || {};
  const result = item.result || {};
  return result.target_image || payload.target_image || `${payload.image_name || "-"}:${payload.target_tag || "latest"}`;
}

function imageRequestSummary(item) {
  const p = item.payload || {};
  return `${sourceRegistryFor(p)} / ${sourceImageFor(item)} -> ${targetRegistryFor(p)} / ${targetImageFor(item)}`;
}

function prettyJson(value) {
  try {
    return JSON.stringify(value || {}, null, 2);
  } catch {
    return "{}";
  }
}

function openDetail(item) {
  selected.value = item;
  showDetail.value = true;
}

async function approveRequest(item) {
  const message =
    isImageRequest(item) && item.payload?.allow_overwrite
      ? "该申请允许覆盖目标标签，确定同意并立即执行吗？"
      : "确定同意该申请并立即执行吗？";
  const ok = await showConfirm({
    title: "同意申请",
    message,
    confirmText: "同意",
  });
  if (!ok) return;
  try {
    await axios.post(`/api/team-approval-requests/${item.request_id}/approve`, {});
    toastSuccess("申请已同意，任务开始执行");
    await loadRequests();
  } catch (e) {
    toastApiError(e, "同意申请失败");
  }
}

function openRejectDialog(item) {
  rejectTarget.value = item;
  rejectNote.value = "";
  showReject.value = true;
}

async function rejectRequest() {
  if (!rejectTarget.value) return;
  rejecting.value = true;
  try {
    await axios.post(`/api/team-approval-requests/${rejectTarget.value.request_id}/reject`, {
      review_note: rejectNote.value,
    });
    toastSuccess("申请已驳回");
    showReject.value = false;
    await loadRequests();
  } catch (e) {
    toastApiError(e, "驳回申请失败");
  } finally {
    rejecting.value = false;
  }
}

onMounted(loadRequests);
</script>
