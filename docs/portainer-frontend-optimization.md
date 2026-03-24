# Portainer 前端页面优化方案

## 一、当前问题分析

### 1.1 AgentHostManager.vue 问题

**当前状态**:
- ✅ 已有Portainer主机类型支持
- ✅ 已有自动加载Endpoint功能
- ❌ 测试连接按钮位置不明显
- ❌ 缺少连接状态实时反馈
- ❌ Endpoint选择体验可以优化

**核心代码位置**:
- 文件: `frontend/src/components/AgentHostManager.vue`
- 行号: 700-778 (Portainer配置表单)

### 1.2 DeployTaskManager.vue 问题

**当前状态**:
- ✅ 已有Stack部署模式支持
- ❌ 缺少Portainer Stack选择功能
- ❌ 无法查看Portainer中已有的Stack
- ❌ 部署时无法指定更新特定Stack

**核心代码位置**:
- 文件: `frontend/src/components/DeployTaskManager.vue`
- 行号: 240-468 (部署方式选择)
- 行号: 1302-1540 (编辑模式部署方式)

---

## 二、前端优化方案

### 改动1: 优化 Portainer 主机添加流程

#### 文件位置
`frontend/src/components/AgentHostManager.vue`

#### 改动内容

**1. 添加连接状态实时反馈**

```vue
<!-- 在 line 700-728 之间修改 Portainer 配置区域 -->
<div v-if="hostForm.host_type === 'portainer'">
  <!-- Portainer API URL -->
  <div class="mb-3">
    <label class="form-label">
      Portainer API URL <span class="text-danger">*</span>
    </label>
    <div class="input-group">
      <input 
        type="text" 
        class="form-control form-control-sm" 
        v-model="hostForm.portainer_url"
        placeholder="http://portainer.example.com:9000"
        @blur="validatePortainerUrl"
        required
      />
      <span class="input-group-text">
        <i :class="urlValidationIcon" :style="{ color: urlValidationColor }"></i>
      </span>
    </div>
    <small class="text-muted">Portainer 服务器的 API 地址</small>
    <small v-if="urlValidationError" class="text-danger d-block">
      {{ urlValidationError }}
    </small>
  </div>

  <!-- Portainer API Key -->
  <div class="mb-3">
    <label class="form-label">
      Portainer API Key <span class="text-danger">*</span>
    </label>
    <div class="input-group">
      <input 
        type="password" 
        class="form-control form-control-sm" 
        v-model="hostForm.portainer_api_key"
        placeholder="ptc_xxxxxxxxxxxxx"
        required
      />
      <button 
        type="button" 
        class="btn btn-sm btn-outline-primary"
        @click="testPortainerConnection"
        :disabled="testingConnection || !hostForm.portainer_url || !hostForm.portainer_api_key"
      >
        <span v-if="testingConnection" class="spinner-border spinner-border-sm"></span>
        <i v-else class="fas fa-plug"></i>
        {{ testingConnection ? '测试中...' : '测试连接' }}
      </button>
    </div>
    <small class="text-muted">在 Portainer 设置中生成的 API Key</small>
    
    <!-- 连接测试结果 -->
    <div v-if="connectionTestResult" class="mt-2">
      <div v-if="connectionTestResult.success" class="alert alert-success py-1 mb-0">
        <i class="fas fa-check-circle me-1"></i>
        {{ connectionTestResult.message }}
      </div>
      <div v-else class="alert alert-danger py-1 mb-0">
        <i class="fas fa-times-circle me-1"></i>
        {{ connectionTestResult.message }}
      </div>
    </div>
  </div>

  <!-- Endpoint 选择 -->
  <div class="mb-3">
    <label class="form-label">
      Endpoint <span class="text-danger">*</span>
    </label>
    <div class="input-group">
      <select 
        class="form-select form-control-sm" 
        v-model.number="hostForm.portainer_endpoint_id"
        :disabled="loadingEndpoints || availableEndpoints.length === 0"
        required
      >
        <option value="" disabled>
          {{ loadingEndpoints ? '加载中...' : '请选择 Endpoint' }}
        </option>
        <option v-for="ep in availableEndpoints" :key="ep.id" :value="ep.id">
          {{ ep.name }} (ID: {{ ep.id }}) - {{ ep.type || 'Docker' }}
        </option>
      </select>
      <button 
        type="button" 
        class="btn btn-sm btn-outline-secondary" 
        @click="loadEndpoints"
        :disabled="loadingEndpoints || !hostForm.portainer_url || !hostForm.portainer_api_key"
        title="刷新 Endpoints 列表"
      >
        <span v-if="loadingEndpoints" class="spinner-border spinner-border-sm"></span>
        <i v-else class="fas fa-sync-alt"></i>
      </button>
    </div>
    <small class="text-muted">
      <span v-if="availableEndpoints.length > 0" class="text-success">
        <i class="fas fa-check me-1"></i>已加载 {{ availableEndpoints.length }} 个 Endpoint
      </span>
      <span v-else-if="hostForm.portainer_url && hostForm.portainer_api_key">
        点击刷新按钮加载 Endpoints 列表
      </span>
    </small>
  </div>
</div>
```

**2. 在 `<script>` 部分添加新方法和数据**

```javascript
data() {
  return {
    // ... 现有数据 ...
    
    // 新增: URL 验证
    urlValidationError: '',
    urlValidationIcon: 'fas fa-question-circle',
    urlValidationColor: '#6c757d',
    
    // 新增: 连接测试结果
    connectionTestResult: null
  }
},

methods: {
  // ... 现有方法 ...
  
  // 新增: URL 验证
  validatePortainerUrl() {
    const url = this.hostForm.portainer_url.trim()
    if (!url) {
      this.urlValidationError = ''
      this.urlValidationIcon = 'fas fa-question-circle'
      this.urlValidationColor = '#6c757d'
      return
    }
    
    // 验证URL格式
    try {
      const urlObj = new URL(url)
      if (urlObj.protocol !== 'http:' && urlObj.protocol !== 'https:') {
        throw new Error('URL必须以 http:// 或 https:// 开头')
      }
      
      this.urlValidationError = ''
      this.urlValidationIcon = 'fas fa-check-circle'
      this.urlValidationColor = '#28a745'
    } catch (error) {
      this.urlValidationError = error.message
      this.urlValidationIcon = 'fas fa-times-circle'
      this.urlValidationColor = '#dc3545'
    }
  },
  
  // 修改: 测试连接 - 添加结果反馈
  async testPortainerConnection() {
    if (!this.hostForm.portainer_url || !this.hostForm.portainer_api_key || 
        this.hostForm.portainer_endpoint_id === null || this.hostForm.portainer_endpoint_id === undefined) {
      this.connectionTestResult = {
        success: false,
        message: '请填写完整的 Portainer 配置信息'
      }
      return
    }
    
    this.testingConnection = true
    this.connectionTestResult = null
    
    try {
      const res = await axios.post('/api/agent-hosts/test-portainer', {
        portainer_url: this.hostForm.portainer_url,
        api_key: this.hostForm.portainer_api_key,
        endpoint_id: this.hostForm.portainer_endpoint_id
      }, {
        timeout: 15000
      })
      
      if (res.data.success) {
        this.connectionTestResult = {
          success: true,
          message: '连接测试成功!Portainer API 可访问'
        }
        // 自动加载 Endpoints
        if (this.availableEndpoints.length === 0) {
          await this.loadEndpoints()
        }
      } else {
        let errorMsg = res.data.message || '未知错误'
        if (res.data.available_endpoints && res.data.available_endpoints.length > 0) {
          errorMsg += ' (可用Endpoints: ' + res.data.available_endpoints.map(ep => ep.name).join(', ') + ')'
        }
        this.connectionTestResult = {
          success: false,
          message: errorMsg
        }
      }
    } catch (error) {
      console.error('测试连接失败:', error)
      let errorMsg = '连接失败: '
      if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
        errorMsg += '连接超时,请检查URL是否正确'
      } else {
        errorMsg += (error.response?.data?.detail || error.message)
      }
      this.connectionTestResult = {
        success: false,
        message: errorMsg
      }
    } finally {
      this.testingConnection = false
    }
  },
  
  // 修改: 自动加载 Endpoints - 成功后自动测试连接
  async autoLoadEndpoints() {
    if (this.hostForm.host_type === 'portainer' && 
        this.hostForm.portainer_url && 
        this.hostForm.portainer_api_key &&
        this.availableEndpoints.length === 0) {
      await this.loadEndpoints()
      
      // 如果自动加载成功且只有一个Endpoint,自动测试连接
      if (this.availableEndpoints.length === 1) {
        this.hostForm.portainer_endpoint_id = this.availableEndpoints[0].id
        await this.testPortainerConnection()
      }
    }
  }
}
```

**改动说明**:
1. **URL实时验证**: 输入框失焦时验证URL格式,显示图标反馈
2. **测试连接按钮**: 移到API Key输入框右侧,更明显
3. **连接状态反馈**: 在API Key下方显示测试结果(成功/失败)
4. **Endpoint优化**: 显示Endpoint类型,自动选择唯一Endpoint

---

### 改动2: 新增 Portainer Stack 选择功能

#### 文件位置
`frontend/src/components/DeployTaskManager.vue`

#### 改动内容

**1. 在部署方式选择区域添加 Stack 选择**

```vue
<!-- 在 line 240-468 之间修改 -->
<div class="card-body">
  <div class="mb-3">
    <label class="form-label"
      >部署方式 <span class="text-danger">*</span></label
    >
    <div class="btn-group w-100" role="group">
      <!-- Docker Run 模式 -->
      <input
        type="radio"
        class="btn-check"
        id="deploy-mode-run"
        v-model="simpleForm.deployMode"
        value="docker-run"
      />
      <label class="btn btn-outline-secondary" for="deploy-mode-run">
        <i class="fas fa-play me-1"></i> Docker Run
      </label>

      <!-- Docker Compose 模式 -->
      <input
        type="radio"
        class="btn-check"
        id="deploy-mode-compose"
        v-model="simpleForm.deployMode"
        value="docker-compose"
      />
      <label class="btn btn-outline-secondary" for="deploy-mode-compose">
        <i class="fab fa-docker me-1"></i> Docker Compose
      </label>
    </div>
    <small class="text-muted d-block mt-1">
      <span v-if="simpleForm.deployMode === 'docker-run'">
        单容器部署模式,适合简单应用
      </span>
      <span v-else>
        多容器编排部署,适合复杂应用
      </span>
    </small>
  </div>

  <!-- Portainer Stack 选择 (仅当主机类型为 Portainer 时显示) -->
  <div 
    v-if="selectedHostType === 'portainer' && simpleForm.deployMode === 'docker-compose'" 
    class="mb-3"
  >
    <label class="form-label">
      Stack 部署策略 <span class="text-danger">*</span>
    </label>
    <div class="btn-group w-100 mb-2" role="group">
      <input
        type="radio"
        class="btn-check"
        id="stack-strategy-create"
        v-model="simpleForm.stackStrategy"
        value="create"
      />
      <label class="btn btn-outline-primary" for="stack-strategy-create">
        <i class="fas fa-plus me-1"></i> 创建新 Stack
      </label>

      <input
        type="radio"
        class="btn-check"
        id="stack-strategy-update"
        v-model="simpleForm.stackStrategy"
        value="update"
      />
      <label class="btn btn-outline-primary" for="stack-strategy-update">
        <i class="fas fa-sync me-1"></i> 更新已有 Stack
      </label>
    </div>

    <!-- Stack 选择 (当选择更新策略时显示) -->
    <div v-if="simpleForm.stackStrategy === 'update'" class="mt-2">
      <div class="input-group">
        <select 
          class="form-select form-control-sm" 
          v-model="simpleForm.selectedStackId"
          @change="loadStackDetails"
          :disabled="loadingStacks"
        >
          <option value="" disabled>请选择要更新的 Stack</option>
          <option v-for="stack in availableStacks" :key="stack.id" :value="stack.id">
            {{ stack.name }} 
            <span v-if="stack.status === 1" class="text-success">(运行中)</span>
            <span v-else class="text-secondary">(已停止)</span>
          </option>
        </select>
        <button 
          type="button" 
          class="btn btn-sm btn-outline-secondary"
          @click="loadAvailableStacks"
          :disabled="loadingStacks"
          title="刷新 Stack 列表"
        >
          <span v-if="loadingStacks" class="spinner-border spinner-border-sm"></span>
          <i v-else class="fas fa-sync-alt"></i>
        </button>
      </div>
      <small class="text-muted d-block mt-1">
        <span v-if="availableStacks.length > 0">
          已加载 {{ availableStacks.length }} 个 Stack
        </span>
        <span v-else>
          点击刷新按钮加载 Stack 列表
        </span>
      </small>

      <!-- Stack 详情预览 -->
      <div v-if="selectedStackDetails" class="mt-2 p-2 bg-light rounded">
        <div class="d-flex justify-content-between align-items-center mb-1">
          <strong>{{ selectedStackDetails.name }}</strong>
          <span 
            class="badge" 
            :class="selectedStackDetails.status === 1 ? 'bg-success' : 'bg-secondary'"
          >
            {{ selectedStackDetails.status === 1 ? '运行中' : '已停止' }}
          </span>
        </div>
        <div class="small text-muted">
          <div>创建时间: {{ formatTime(selectedStackDetails.created_at) }}</div>
          <div>更新时间: {{ formatTime(selectedStackDetails.updated_at) }}</div>
        </div>
        <button 
          type="button" 
          class="btn btn-sm btn-link p-0 mt-1"
          @click="showStackComposePreview = true"
        >
          <i class="fas fa-eye me-1"></i> 查看当前配置
        </button>
      </div>
    </div>

    <!-- 新 Stack 名称 (当选择创建策略时显示) -->
    <div v-if="simpleForm.stackStrategy === 'create'" class="mt-2">
      <label class="form-label small">Stack 名称</label>
      <input 
        type="text" 
        class="form-control form-control-sm"
        v-model="simpleForm.newStackName"
        placeholder="my-app-stack"
      />
      <small class="text-muted">Stack 名称将用于标识和管理部署</small>
    </div>
  </div>

  <!-- Compose 内容编辑 -->
  <div class="mb-3">
    <label class="form-label"
      >Compose 内容 <span class="text-danger">*</span></label
    >
    <textarea
      v-model="simpleForm.composeContent"
      class="form-control font-monospace"
      rows="10"
      placeholder="version: '3.8'&#10;services:&#10;  app:&#10;    image: nginx:latest&#10;    ports:&#10;      - '80:80'"
    ></textarea>
    <small class="text-muted">
      输入 docker-compose.yml 文件内容
    </small>
  </div>
</div>
```

**2. 在 `<script>` 部分添加数据和方法**

```javascript
data() {
  return {
    // ... 现有数据 ...
    
    // 新增: Portainer Stack 相关
    simpleForm: {
      // ... 现有字段 ...
      stackStrategy: 'create', // create 或 update
      selectedStackId: null,
      newStackName: ''
    },
    
    availableStacks: [],
    loadingStacks: false,
    selectedStackDetails: null,
    showStackComposePreview: false
  }
},

computed: {
  // 新增: 判断选中的主机类型
  selectedHostType() {
    if (!this.simpleForm.target_host_id) return null
    const host = this.hosts.find(h => h.host_id === this.simpleForm.target_host_id)
    return host?.host_type || 'agent'
  }
},

methods: {
  // ... 现有方法 ...
  
  // 新增: 加载可用的 Stack 列表
  async loadAvailableStacks() {
    if (!this.simpleForm.target_host_id) {
      alert('请先选择目标主机')
      return
    }
    
    this.loadingStacks = true
    this.availableStacks = []
    
    try {
      const res = await axios.get(`/api/agent-hosts/${this.simpleForm.target_host_id}/stacks`)
      if (res.data.success) {
        this.availableStacks = res.data.stacks || []
        if (this.availableStacks.length === 0) {
          alert('该主机下没有可用的 Stack')
        }
      } else {
        alert('加载 Stack 列表失败: ' + (res.data.message || '未知错误'))
      }
    } catch (error) {
      console.error('加载 Stack 列表失败:', error)
      alert('加载 Stack 列表失败: ' + (error.response?.data?.detail || error.message))
    } finally {
      this.loadingStacks = false
    }
  },
  
  // 新增: 加载 Stack 详情
  async loadStackDetails() {
    if (!this.simpleForm.selectedStackId) {
      this.selectedStackDetails = null
      return
    }
    
    try {
      const res = await axios.get(
        `/api/agent-hosts/${this.simpleForm.target_host_id}/stacks/${this.simpleForm.selectedStackId}`
      )
      if (res.data.success) {
        this.selectedStackDetails = res.data.stack
      }
    } catch (error) {
      console.error('加载 Stack 详情失败:', error)
      alert('加载 Stack 详情失败: ' + (error.response?.data?.detail || error.message))
    }
  },
  
  // 修改: 主机选择变化时重置 Stack 相关状态
  onTargetHostChange() {
    // ... 原有逻辑 ...
    
    // 重置 Stack 相关状态
    this.availableStacks = []
    this.selectedStackDetails = null
    this.simpleForm.stackStrategy = 'create'
    this.simpleForm.selectedStackId = null
    this.simpleForm.newStackName = ''
    
    // 如果是 Portainer 主机,自动加载 Stack 列表
    if (this.selectedHostType === 'portainer') {
      this.loadAvailableStacks()
    }
  },
  
  // 修改: 提交部署时包含 Stack 策略
  async submitSimpleCreate() {
    // ... 原有验证逻辑 ...
    
    // 如果是 Portainer 主机的 Stack 模式
    if (this.selectedHostType === 'portainer' && this.simpleForm.deployMode === 'docker-compose') {
      if (this.simpleForm.stackStrategy === 'create') {
        if (!this.simpleForm.newStackName) {
          alert('请输入新 Stack 的名称')
          return
        }
        // 创建新 Stack
        this.simpleForm.stack_name = this.simpleForm.newStackName
        this.simpleForm.stack_action = 'create'
      } else {
        if (!this.simpleForm.selectedStackId) {
          alert('请选择要更新的 Stack')
          return
        }
        // 更新已有 Stack
        this.simpleForm.stack_id = this.simpleForm.selectedStackId
        this.simpleForm.stack_action = 'update'
      }
    }
    
    // ... 提交逻辑 ...
  }
},

watch: {
  // 新增: 监听主机选择变化
  'simpleForm.target_host_id': {
    handler(newVal, oldVal) {
      if (newVal !== oldVal && newVal) {
        this.onTargetHostChange()
      }
    }
  }
}
```

**改动说明**:
1. **Stack策略选择**: Portainer主机下可选择"创建新Stack"或"更新已有Stack"
2. **Stack列表显示**: 显示Stack名称和状态(运行中/已停止)
3. **Stack详情预览**: 选择Stack后显示详细信息
4. **自动加载**: 选择Portainer主机后自动加载Stack列表

---

## 三、改动影响范围

### 3.1 AgentHostManager.vue

| 改动项 | 影响范围 | 风险等级 |
|--------|----------|----------|
| URL实时验证 | 用户体验 | 低 |
| 测试连接按钮位置 | UI布局 | 低 |
| 连接状态反馈 | UI展示 | 低 |
| Endpoint选择优化 | UI展示 | 低 |

### 3.2 DeployTaskManager.vue

| 改动项 | 影响范围 | 风险等级 |
|--------|----------|----------|
| Stack策略选择 | 部署流程 | 中 |
| Stack列表加载 | 数据获取 | 中 |
| Stack详情预览 | UI展示 | 低 |
| 部署参数调整 | 部署逻辑 | 中 |

---

## 四、验收标准

### 4.1 AgentHostManager.vue 验收

- [ ] URL输入后实时显示验证状态(图标+颜色)
- [ ] 测试连接按钮显示在API Key右侧
- [ ] 测试连接后显示成功/失败结果
- [ ] Endpoint列表显示类型信息
- [ ] 只有一个Endpoint时自动选择
- [ ] 自动选择后自动测试连接

### 4.2 DeployTaskManager.vue 验收

- [ ] Portainer主机下显示Stack策略选择
- [ ] 选择"更新Stack"后加载Stack列表
- [ ] Stack列表正确显示名称和状态
- [ ] 选择Stack后显示详情预览
- [ ] 创建Stack时输入名称
- [ ] 部署参数正确传递到后端

---

## 五、测试建议

### 5.1 主机添加测试

```
1. 输入错误格式的URL → 显示红色×图标
2. 输入正确格式的URL → 显示绿色✓图标
3. 点击测试连接 → 显示测试结果
4. 加载Endpoint → 显示Endpoint列表
5. 选择Endpoint → 保存主机成功
```

### 5.2 Stack部署测试

```
1. 选择Portainer主机 → 显示Stack策略选择
2. 选择"更新Stack" → 自动加载Stack列表
3. 选择Stack → 显示详情预览
4. 提交部署 → 验证参数正确
5. 选择"创建Stack" → 输入Stack名称
6. 提交部署 → 创建新Stack成功
```

---

## 六、回滚方案

如果出现问题,可以快速回滚:

```bash
# 前端回滚
git checkout HEAD -- frontend/src/components/AgentHostManager.vue
git checkout HEAD -- frontend/src/components/DeployTaskManager.vue
```

---

## 七、关键代码位置总结

| 文件 | 改动位置 | 改动类型 |
|------|----------|----------|
| `AgentHostManager.vue` | 行700-778 | 修改UI |
| `AgentHostManager.vue` | data() | 新增数据 |
| `AgentHostManager.vue` | methods | 新增方法 |
| `DeployTaskManager.vue` | 行240-468 | 新增UI |
| `DeployTaskManager.vue` | data() | 新增数据 |
| `DeployTaskManager.vue` | methods | 新增方法 |
| `DeployTaskManager.vue` | computed | 新增计算属性 |
| `DeployTaskManager.vue` | watch | 新增监听器 |
