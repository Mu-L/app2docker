<template>
  <FormDialog
    :model-value="show"
    title="用户中心"
    icon="user-circle"
    size="lg"
    @update:model-value="onDialogUpdate"
  >
    <AlertBanner
      v-if="requirePasswordChange"
      message="检测到您使用的是默认密码，为了安全起见，请先修改密码。"
      variant="warning"
    />

    <div v-if="!requirePasswordChange" class="mb-4">
      <h4 class="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900">
        <AppIcon  name="user" class="text-blue-600" />
        用户信息
      </h4>
      <Card>
        <CardContent class="flex items-center gap-3 p-4">
          <AppIcon  name="user-circle" class="text-3xl text-blue-600" />
          <div>
            <div class="font-semibold text-slate-900">{{ username }}</div>
            <p v-if="isGlobalAdmin" class="text-xs text-slate-500">系统管理员</p>
            <p v-else-if="teamStore.activeTeamRole" class="text-xs text-slate-500">
              {{ teamRoleLabel(teamStore.activeTeamRole) }}
            </p>
          </div>
        </CardContent>
      </Card>
    </div>

    <div v-if="!requirePasswordChange" class="mb-4 flex gap-1 border-b border-slate-200">
      <button
        type="button"
        class="border-b-2 px-4 py-2 text-sm font-medium transition"
        :class="activeTab === 'password'
            ? 'border-blue-600 text-blue-600'
            : 'border-transparent text-slate-500 hover:text-slate-800'"
        @click="activeTab = 'password'"
      >
        修改密码
      </button>
      <button
        type="button"
        class="border-b-2 px-4 py-2 text-sm font-medium transition"
        :class="activeTab === 'appkeys'
            ? 'border-blue-600 text-blue-600'
            : 'border-transparent text-slate-500 hover:text-slate-800'"
        @click="switchToAppKeys"
      >
        CLI 认证
      </button>
    </div>

    <div v-if="activeTab === 'password' || requirePasswordChange">
      <h4
        v-if="!requirePasswordChange"
        class="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900"
      >
        <AppIcon  name="key" class="text-blue-600" />
        修改密码
      </h4>
      <form class="space-y-4" @submit.prevent="handleChangePassword">
        <div class="space-y-2">
          <Label>当前密码 <span class="text-red-500">*</span></Label>
          <Input
            v-model="form.oldPassword"
            type="password"
            placeholder="请输入当前密码"
            required
            autocomplete="current-password"
          />
        </div>
        <div class="space-y-2">
          <Label>新密码 <span class="text-red-500">*</span></Label>
          <Input
            v-model="form.newPassword"
            type="password"
            placeholder="请输入新密码（至少 6 位）"
            required
            minlength="6"
            autocomplete="new-password"
          />
          <p class="text-xs text-slate-500">密码长度至少 6 位</p>
        </div>
        <div class="space-y-2">
          <Label>确认新密码 <span class="text-red-500">*</span></Label>
          <Input
            v-model="form.confirmPassword"
            type="password"
            placeholder="请再次输入新密码"
            required
            minlength="6"
            autocomplete="new-password"
          />
        </div>
      </form>
    </div>

    <div v-else-if="activeTab === 'appkeys' && !requirePasswordChange">
      <div class="mb-3 flex items-center justify-between">
        <h4 class="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <AppIcon name="fingerprint" class="text-blue-600" />
          唯一证书凭证
        </h4>
        <Button size="sm" type="button" @click="showCredentialForm = !showCredentialForm">
          <AppIcon name="plus" /> 上传公钥
        </Button>
      </div>
      <p class="mb-3 text-xs text-slate-500">
        上传本机 SSH 公钥（.pub），私钥只保留在本机。同一公钥只能绑定一个账号。
      </p>

      <Card v-if="showCredentialForm" class="mb-4">
        <CardContent class="space-y-3 p-4">
          <div class="space-y-2">
            <Label>名称</Label>
            <Input v-model="newCredential.name" placeholder="例如：办公电脑" maxlength="255" />
          </div>
          <div class="space-y-2">
            <Label>SSH 公钥</Label>
            <input type="file" accept=".pub,.pem,text/plain" class="block w-full text-sm" @change="readPublicKeyFile" />
            <textarea
              v-model="newCredential.publicKey"
              rows="3"
              class="w-full rounded-md border border-slate-200 px-3 py-2 font-mono text-xs"
              placeholder="ssh-ed25519 AAAA..."
            />
          </div>
          <div class="space-y-2">
            <Label>过期时间（可选）</Label>
            <Input v-model="newCredential.expiresAt" type="datetime-local" />
          </div>
          <Button
            size="sm"
            type="button"
            :disabled="creatingCredential || !newCredential.name.trim() || !newCredential.publicKey.trim()"
            @click="createCredential"
          >
            <AppIcon v-if="creatingCredential" name="spinner" spin />
            绑定到当前账号
          </Button>
        </CardContent>
      </Card>

      <div v-if="credentialsLoading" class="flex items-center gap-2 py-4 text-sm text-slate-500">
        <AppIcon name="spinner" spin /> 加载中…
      </div>
      <EmptyState v-else-if="credentials.length === 0" message="暂无证书凭证" icon="fingerprint" />
      <Table v-else min-width-class="min-w-[48rem]" class="mb-6">
        <TableHeader>
          <TableRow>
            <TableHead>名称</TableHead>
            <TableHead>凭证 ID</TableHead>
            <TableHead>唯一指纹</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>最后使用</TableHead>
            <TableHead class="text-end">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="item in credentials" :key="item.credential_id">
            <TableCell>{{ item.name }}</TableCell>
            <TableCell><code class="text-xs">{{ item.credential_id }}</code></TableCell>
            <TableCell><code class="text-xs">{{ item.fingerprint }}</code></TableCell>
            <TableCell>
              <Badge :variant="item.enabled ? 'success' : 'default'">{{ item.enabled ? "启用" : "禁用" }}</Badge>
            </TableCell>
            <TableCell>{{ formatTime(item.last_used_at) }}</TableCell>
            <TableCell class="text-end">
              <div class="flex justify-end gap-1">
                <Button variant="outline" size="sm" type="button" @click="toggleCredential(item.credential_id)">
                  {{ item.enabled ? "禁用" : "启用" }}
                </Button>
                <Button variant="destructive" size="sm" type="button" @click="removeCredential(item.credential_id)">删除</Button>
              </div>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>

      <div class="my-5 border-t border-slate-200"></div>
      <div class="mb-3 flex items-center justify-between">
        <h4 class="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <AppIcon  name="fingerprint" class="text-blue-600" />
          API Key（可选）
        </h4>
        <Button
          size="sm"
          type="button"
          :disabled="appKeysLoading"
          @click="showCreateForm = !showCreateForm"
        >
          <AppIcon  name="plus" />
          创建 API Key
        </Button>
      </div>

      <Card v-if="showCreateForm" class="mb-4">
        <CardContent class="space-y-3 p-4">
          <div class="space-y-2">
            <Label>名称</Label>
            <Input
              v-model="newAppKey.name"
              placeholder="例如：CI 调用密钥"
              maxlength="255"
            />
          </div>
          <div class="space-y-2">
            <Label>过期时间（可选）</Label>
            <Input v-model="newAppKey.expiresAt" type="datetime-local" />
          </div>
          <Button
            size="sm"
            type="button"
            :disabled="creatingAppKey || !newAppKey.name.trim()"
            @click="createAppKey"
          >
            <AppIcon v-if="creatingAppKey"  name="spinner" spin />
            生成密钥
          </Button>
        </CardContent>
      </Card>

      <AlertBanner
        v-if="createdAppKey"
        :message="`请立即复制，该密钥仅展示一次：${createdAppKey}`"
        variant="warning"
      />

      <div
        v-if="appKeysLoading"
        class="flex items-center gap-2 py-6 text-sm text-slate-500"
      >
        <AppIcon  name="spinner" spin />
        加载中…
      </div>
      <EmptyState v-else-if="appKeys.length === 0" message="暂无 API 密钥" icon="fingerprint" />
      <Table v-else min-width-class="min-w-[48rem]">
          <TableHeader>
            <TableRow>
              <TableHead>名称</TableHead>
              <TableHead>前缀</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>最后使用</TableHead>
              <TableHead>过期时间</TableHead>
              <TableHead class="text-end">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="item in appKeys" :key="item.key_id">
              <TableCell>{{ item.name }}</TableCell>
              <TableCell>
                <code class="rounded bg-slate-100 px-1 text-xs">{{ item.key_prefix }}</code>
              </TableCell>
              <TableCell>
                <Badge :variant="item.enabled ? 'success' : 'default'">
                  {{ item.enabled ?"启用" :"禁用" }}
                </Badge>
              </TableCell>
              <TableCell class="text-slate-600">{{ formatTime(item.last_used_at) }}</TableCell>
              <TableCell class="text-slate-600">{{ formatTime(item.expires_at) }}</TableCell>
              <TableCell class="text-end">
                <div class="flex justify-end gap-1">
                  <Button
                    variant="outline"
                    size="sm"
                    type="button"
                    @click="toggleAppKey(item.key_id)"
                  >
                    {{ item.enabled ?"禁用" :"启用" }}
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    type="button"
                    @click="removeAppKey(item.key_id)"
                  >
                    删除
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          </TableBody>
      </Table>
    </div>

    <AlertBanner :message="error" class="mt-3" />
    <AlertBanner :message="success" variant="success" class="mt-3" />

    <template #footer>
      <Button v-if="!requirePasswordChange" variant="outline" type="button" @click="close">
        关闭
      </Button>
      <Button
        type="button"
        :disabled="
          (activeTab === 'password' || requirePasswordChange) && (loading || !canSubmit)"
        @click="handlePrimaryAction"
      >
        <AppIcon v-if="loading"  name="spinner" spin />
        {{
          activeTab ==="password" || requirePasswordChange
            ? loading
              ?"修改中…"
              :"修改密码"
            :"确定"
        }}
      </Button>
    </template>
  </FormDialog>
</template>

<script setup>
import { showConfirm } from "@/composables/useConfirm";

import { computed, ref, watch } from "vue";
import axios from "axios";
import FormDialog from "@/components/ui/dialog/FormDialog.vue";
import EmptyState from "@/components/ui/EmptyState.vue";
import AlertBanner from "@/components/ui/AlertBanner.vue";
import Button from "@/components/ui/button/Button.vue";
import Input from "@/components/ui/input/Input.vue";
import Label from "@/components/ui/label/Label.vue";
import { Badge } from "@/components/ui/badge";
import Card from "@/components/ui/card/Card.vue";
import CardContent from "@/components/ui/card/CardContent.vue";
import Table from "@/components/ui/table/Table.vue";
import TableHeader from "@/components/ui/table/TableHeader.vue";
import TableBody from "@/components/ui/table/TableBody.vue";
import TableRow from "@/components/ui/table/TableRow.vue";
import TableHead from "@/components/ui/table/TableHead.vue";
import TableCell from "@/components/ui/table/TableCell.vue";
import { useTeamStore } from "@/stores/team";
import { useAuthStore } from "@/stores/auth";

const props = defineProps({
  show: {
    type: Boolean,
    default: false,
  },
  username: {
    type: String,
    default:"",
  },
  requirePasswordChange: {
    type: Boolean,
    default: false,
  },
  initialTab: {
    type: String,
    default:"password",
  },
});

const emit = defineEmits(["update:show","password-changed"]);

const teamStore = useTeamStore();
const authStore = useAuthStore();

const isGlobalAdmin = computed(() => authStore.isGlobalAdmin);

function teamRoleLabel(role) {
  const map = { owner:"所有者", admin:"管理员", member:"成员" };
  return map[role] || role;
}

const form = ref({
  oldPassword:"",
  newPassword:"",
  confirmPassword:"",
});

const loading = ref(false);
const error = ref("");
const success = ref("");
const activeTab = ref("password");
const appKeys = ref([]);
const appKeysLoading = ref(false);
const credentials = ref([]);
const credentialsLoading = ref(false);
const showCredentialForm = ref(false);
const creatingCredential = ref(false);
const newCredential = ref({ name:"", publicKey:"", expiresAt:"" });
const showCreateForm = ref(false);
const creatingAppKey = ref(false);
const createdAppKey = ref("");
const newAppKey = ref({
  name:"",
  expiresAt:"",
});

const canSubmit = computed(() => {
  return (
    form.value.oldPassword &&
    form.value.newPassword &&
    form.value.confirmPassword &&
    form.value.newPassword.length >= 6 &&
    form.value.newPassword === form.value.confirmPassword
  );
});

function onDialogUpdate(value) {
  emit("update:show", value);
  if (!value) {
    resetState();
  }
}

function close() {
  emit("update:show", false);
  resetState();
}

function resetState() {
  form.value = {
    oldPassword:"",
    newPassword:"",
    confirmPassword:"",
  };
  const tab = props.initialTab;
  activeTab.value = tab ==="appkeys" ?"appkeys" :"password";
  appKeys.value = [];
  credentials.value = [];
  showCredentialForm.value = false;
  newCredential.value = { name:"", publicKey:"", expiresAt:"" };
  showCreateForm.value = false;
  createdAppKey.value ="";
  newAppKey.value = { name:"", expiresAt:"" };
  error.value ="";
  success.value ="";
}

function handlePrimaryAction() {
  if (activeTab.value ==="password" || props.requirePasswordChange) {
    handleChangePassword();
  } else {
    close();
  }
}

async function switchToAppKeys() {
  activeTab.value ="appkeys";
  await Promise.all([loadCredentials(), loadAppKeys()]);
}

function formatTime(value) {
  if (!value) return"—";
  try {
    return new Date(value).toLocaleString("zh-CN");
  } catch {
    return value;
  }
}

async function loadAppKeys() {
  appKeysLoading.value = true;
  error.value ="";
  try {
    const res = await axios.get("/api/user/api-keys");
    appKeys.value = res.data?.api_keys || [];
  } catch (err) {
    error.value = err.response?.data?.detail || err.message ||"加载 API 密钥失败";
  } finally {
    appKeysLoading.value = false;
  }
}

async function createAppKey() {
  if (!newAppKey.value.name.trim()) return;
  creatingAppKey.value = true;
  error.value ="";
  success.value ="";
  try {
    const payload = { name: newAppKey.value.name.trim() };
    if (newAppKey.value.expiresAt) {
      payload.expires_at = new Date(newAppKey.value.expiresAt).toISOString();
    }
    const res = await axios.post("/api/user/api-keys", payload);
    createdAppKey.value = res.data?.api_key ||"";
    success.value ="API 密钥创建成功";
    newAppKey.value = { name:"", expiresAt:"" };
    showCreateForm.value = false;
    await loadAppKeys();
  } catch (err) {
    error.value = err.response?.data?.detail || err.message ||"创建 API 密钥失败";
  } finally {
    creatingAppKey.value = false;
  }
}

async function toggleAppKey(keyId) {
  error.value ="";
  success.value ="";
  try {
    await axios.put(`/api/user/api-keys/${keyId}/toggle`);
    success.value ="API 密钥状态已更新";
    await loadAppKeys();
  } catch (err) {
    error.value = err.response?.data?.detail || err.message ||"更新 API 密钥状态失败";
  }
}

async function removeAppKey(keyId) {
  if (!(await showConfirm({ message:"确定删除该 API 密钥吗？删除后不可恢复。", danger: true }))) return;
  error.value ="";
  success.value ="";
  try {
    await axios.delete(`/api/user/api-keys/${keyId}`);
    success.value ="API 密钥已删除";
    await loadAppKeys();
  } catch (err) {
    error.value = err.response?.data?.detail || err.message ||"删除 API 密钥失败";
  }
}

async function loadCredentials() {
  credentialsLoading.value = true;
  try {
    const res = await axios.get("/api/user/cli-credentials");
    credentials.value = res.data?.credentials || [];
  } catch (err) {
    error.value = err.response?.data?.detail || err.message ||"加载证书凭证失败";
  } finally {
    credentialsLoading.value = false;
  }
}

async function readPublicKeyFile(event) {
  const file = event.target.files?.[0];
  if (file) newCredential.value.publicKey = await file.text();
}

async function createCredential() {
  creatingCredential.value = true;
  error.value ="";
  try {
    const payload = {
      name: newCredential.value.name.trim(),
      public_key: newCredential.value.publicKey.trim(),
    };
    if (newCredential.value.expiresAt) {
      payload.expires_at = new Date(newCredential.value.expiresAt).toISOString();
    }
    await axios.post("/api/user/cli-credentials", payload);
    success.value ="证书凭证已绑定到当前账号";
    newCredential.value = { name:"", publicKey:"", expiresAt:"" };
    showCredentialForm.value = false;
    await loadCredentials();
  } catch (err) {
    error.value = err.response?.data?.detail || err.message ||"绑定证书凭证失败";
  } finally {
    creatingCredential.value = false;
  }
}

async function toggleCredential(credentialId) {
  try {
    await axios.put(`/api/user/cli-credentials/${credentialId}/toggle`);
    await loadCredentials();
  } catch (err) {
    error.value = err.response?.data?.detail || err.message ||"更新证书凭证失败";
  }
}

async function removeCredential(credentialId) {
  if (!(await showConfirm({ message:"确定删除该证书凭证吗？", danger: true }))) return;
  try {
    await axios.delete(`/api/user/cli-credentials/${credentialId}`);
    await loadCredentials();
  } catch (err) {
    error.value = err.response?.data?.detail || err.message ||"删除证书凭证失败";
  }
}

async function handleChangePassword() {
  if (!canSubmit.value) {
    error.value ="请填写完整信息，且新密码长度至少 6 位，两次输入需一致";
    return;
  }

  if (form.value.newPassword !== form.value.confirmPassword) {
    error.value ="两次输入的密码不一致";
    return;
  }

  if (form.value.newPassword.length < 6) {
    error.value ="新密码长度至少 6 位";
    return;
  }

  loading.value = true;
  error.value ="";
  success.value ="";

  try {
    const res = await axios.post("/api/change-password", {
      old_password: form.value.oldPassword,
      new_password: form.value.newPassword,
    });

    if (res.data.success) {
      success.value ="密码修改成功！";
      form.value = {
        oldPassword:"",
        newPassword:"",
        confirmPassword:"",
      };

      if (props.requirePasswordChange) {
        setTimeout(() => {
          emit("password-changed");
          emit("update:show", false);
        }, 1000);
      } else {
        setTimeout(() => {
          success.value ="";
        }, 3000);
      }
    } else {
      error.value = res.data.error ||"修改密码失败";
    }
  } catch (err) {
    error.value = err.response?.data?.error || err.message ||"修改密码失败";
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.show,
  (visible) => {
    if (visible) {
      const tab = props.initialTab;
      activeTab.value = tab ==="appkeys" ?"appkeys" :"password";
      if (activeTab.value ==="appkeys") {
        loadCredentials();
        loadAppKeys();
      }
    } else {
      resetState();
    }
  },
  { immediate: true }
);
</script>
