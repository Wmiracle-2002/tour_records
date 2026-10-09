package com.miracle.footmarks.ui.screen.smartplanning

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.remote.CloudSession
import com.miracle.footmarks.data.remote.RemoteConversation
import com.miracle.footmarks.data.remote.RemoteConversationMessage
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import retrofit2.HttpException
import java.io.IOException
import java.net.SocketTimeoutException
import java.util.UUID
import javax.inject.Inject

enum class ChatRole {
    USER,
    AGENT
}

data class ChatMessage(
    val id: Long,
    val role: ChatRole,
    val text: String,
    val status: String = "completed"
)

data class AgentProgressStep(val id: String, val label: String, val status: String)

data class SmartPlanningUiState(
    val messages: List<ChatMessage> = emptyList(),
    val conversations: List<RemoteConversation> = emptyList(),
    val currentConversationId: String? = null,
    val isLoadingConversations: Boolean = false,
    val isLoadingMessages: Boolean = false,
    val hasOlderMessages: Boolean = false,
    val isLoadingOlderMessages: Boolean = false,
    val draft: String = "",
    val isSending: Boolean = false,
    val streamingStage: String? = null,
    val streamingText: String = "",
    val progressSteps: List<AgentProgressStep> = emptyList(),
    val progressStartedAtMillis: Long? = null,
    val isCreatingConversation: Boolean = false,
    val error: String? = null
) {
    val isCurrentConversationEmpty: Boolean
        get() = currentConversationId != null && messages.isEmpty() &&
            conversations.any { it.id == currentConversationId && it.messageCount == 0 }
}

@HiltViewModel
class SmartPlanningViewModel @Inject constructor(
    private val cloudSession: CloudSession,
    private val savedStateHandle: SavedStateHandle
) : ViewModel() {
    private val _uiState = MutableStateFlow(
        SmartPlanningUiState(draft = savedStateHandle[DRAFT_KEY] ?: "")
    )
    val uiState: StateFlow<SmartPlanningUiState> = _uiState.asStateFlow()

    private var nextMessageId = -2L
    private var revealJob: Job? = null

    init {
        if (cloudSession.isCloudMode) refreshConversations()
    }

    fun updateDraft(value: String) {
        savedStateHandle[DRAFT_KEY] = value
        _uiState.value = _uiState.value.copy(draft = value, error = null)
    }

    fun send() {
        val state = _uiState.value
        if (state.isSending || state.isCreatingConversation) return

        val message = state.draft.trim()
        if (message.isEmpty()) return

        revealJob?.cancel()
        savedStateHandle[DRAFT_KEY] = ""
        _uiState.value = state.copy(
            messages = state.messages + ChatMessage(nextId(), ChatRole.USER, message),
            draft = "",
            isSending = true,
            streamingStage = "正在连接智能规划…",
            streamingText = "",
            progressSteps = listOf(AgentProgressStep("connection", "正在连接智能规划…", "running")),
            progressStartedAtMillis = System.currentTimeMillis(),
            error = null
        )
        viewModelScope.launch {
            try {
                val conversationId = state.currentConversationId
                    ?: cloudSession.createConversation().let { conversation ->
                        val createdId = conversation.id
                        savedStateHandle[CONVERSATION_KEY] = createdId
                        val current = _uiState.value
                        _uiState.value = current.copy(
                            currentConversationId = createdId,
                            conversations = listOf(conversation) + current.conversations.filterNot {
                                it.id == createdId
                            }
                        )
                        createdId
                    }
                val clientMessageId = if (
                    savedStateHandle.get<String>(PENDING_MESSAGE_KEY) == message &&
                    savedStateHandle.get<String>(PENDING_CONVERSATION_KEY) == conversationId
                ) {
                    savedStateHandle.get<String>(PENDING_CLIENT_ID_KEY) ?: UUID.randomUUID().toString()
                } else {
                    UUID.randomUUID().toString()
                }
                savedStateHandle[PENDING_MESSAGE_KEY] = message
                savedStateHandle[PENDING_CONVERSATION_KEY] = conversationId
                savedStateHandle[PENDING_CLIENT_ID_KEY] = clientMessageId
                var previewActive = false
                var receivedText = ""
                cloudSession.streamAgent(
                    message,
                    conversationId,
                    clientMessageId
                ) { event ->
                    val current = _uiState.value
                    if (current.currentConversationId == conversationId) {
                        when (event.name) {
                            "stage" -> {
                                val label = event.message ?: return@streamAgent
                                val id = event.stage ?: label
                                val status = event.status?.takeIf {
                                    it in setOf("running", "success", "degraded", "failed")
                                } ?: "running"
                                val steps = current.progressSteps.filterNot { it.id == "connection" }.toMutableList()
                                val index = steps.indexOfFirst { it.id == id }
                                val step = AgentProgressStep(id, label, status)
                                if (index < 0) steps.add(step) else steps[index] = step
                                _uiState.value = current.copy(streamingStage = label, progressSteps = steps)
                            }
                            "preview" -> {
                                previewActive = true
                                receivedText = event.text ?: ""
                                revealText(conversationId, receivedText)
                            }
                            "content" -> {
                                receivedText = (if (previewActive) "" else receivedText) +
                                    (event.text ?: "")
                                previewActive = false
                                revealText(conversationId, receivedText)
                            }
                        }
                    }
                }
                revealJob?.join()
                savedStateHandle.remove<String>(PENDING_MESSAGE_KEY)
                savedStateHandle.remove<String>(PENDING_CONVERSATION_KEY)
                savedStateHandle.remove<String>(PENDING_CLIENT_ID_KEY)
                if (_uiState.value.currentConversationId == conversationId) {
                    loadMessages(conversationId)
                }
                refreshConversations(selectConversation = false)
                _uiState.value = _uiState.value.copy(
                    isSending = false, streamingStage = null, streamingText = "",
                    progressSteps = emptyList(), progressStartedAtMillis = null
                )
            } catch (error: Exception) {
                revealJob?.cancel()
                val current = _uiState.value
                val restoredDraft = current.draft.ifBlank { message }
                savedStateHandle[DRAFT_KEY] = restoredDraft
                current.currentConversationId?.let { conversationId ->
                    runCatching { loadMessages(conversationId) }
                }
                _uiState.value = _uiState.value.copy(
                    draft = restoredDraft,
                    isSending = false,
                    streamingStage = null,
                    streamingText = "",
                    progressSteps = current.progressSteps.map {
                        if (it.status == "running") it.copy(status = "failed") else it
                    }.let { steps ->
                        if (steps.any { it.status == "failed" }) steps
                        else steps + AgentProgressStep("response", "接收回答", "failed")
                    },
                    error = userMessage(error)
                )
            }
        }
    }

    fun refreshConversations(selectConversation: Boolean = true) {
        if (!cloudSession.isCloudMode) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoadingConversations = true)
            try {
                val conversations = cloudSession.getConversations()
                val savedId = savedStateHandle.get<String>(CONVERSATION_KEY)
                val previousId = _uiState.value.currentConversationId
                val selectedId = when {
                    !selectConversation && previousId != null -> previousId
                    previousId != null && conversations.any { it.id == previousId } -> previousId
                    savedId != null && conversations.any { it.id == savedId } -> savedId
                    else -> conversations.firstOrNull()?.id
                }
                _uiState.value = _uiState.value.copy(
                    conversations = conversations,
                    currentConversationId = selectedId,
                    isLoadingConversations = false
                )
                if (selectedId != null && selectedId != previousId) {
                    savedStateHandle[CONVERSATION_KEY] = selectedId
                    loadMessages(selectedId)
                } else if (selectedId == null && !_uiState.value.isSending) {
                    savedStateHandle[CONVERSATION_KEY] = null
                    _uiState.value = _uiState.value.copy(
                        messages = emptyList(),
                        hasOlderMessages = false,
                        isLoadingMessages = false,
                        isLoadingOlderMessages = false
                    )
                }
            } catch (error: Exception) {
                _uiState.value = _uiState.value.copy(
                    isLoadingConversations = false,
                    error = userMessage(error)
                )
            }
        }
    }

    fun createNewConversation() {
        val state = _uiState.value
        if (state.isCreatingConversation || state.isSending || state.isCurrentConversationEmpty) return
        _uiState.value = state.copy(isCreatingConversation = true, error = null)
        viewModelScope.launch {
            try {
                val conversation = cloudSession.createConversation()
                savedStateHandle[CONVERSATION_KEY] = conversation.id
                _uiState.value = _uiState.value.copy(
                    conversations = listOf(conversation) + _uiState.value.conversations,
                    currentConversationId = conversation.id,
                    messages = emptyList(),
                    hasOlderMessages = false,
                    isLoadingOlderMessages = false,
                    error = null
                )
            } catch (error: Exception) {
                _uiState.value = _uiState.value.copy(error = userMessage(error))
            } finally {
                _uiState.value = _uiState.value.copy(isCreatingConversation = false)
            }
        }
    }

    fun openConversation(conversationId: String) {
        if (_uiState.value.currentConversationId == conversationId) return
        revealJob?.cancel()
        savedStateHandle[CONVERSATION_KEY] = conversationId
        _uiState.value = _uiState.value.copy(
            currentConversationId = conversationId,
            messages = emptyList(),
            hasOlderMessages = false,
            isLoadingMessages = false,
            isLoadingOlderMessages = false,
            streamingStage = null,
            streamingText = "",
            progressSteps = emptyList(), progressStartedAtMillis = null,
            error = null
        )
        viewModelScope.launch {
            runCatching { loadMessages(conversationId) }
                .onFailure { _uiState.value = _uiState.value.copy(error = userMessage(it)) }
        }
    }

    fun deleteConversation(conversationId: String) {
        viewModelScope.launch {
            try {
                cloudSession.deleteConversation(conversationId)
                val remaining = _uiState.value.conversations.filterNot { it.id == conversationId }
                _uiState.value = _uiState.value.copy(conversations = remaining)
                if (_uiState.value.currentConversationId == conversationId) {
                    val nextConversation = remaining.firstOrNull()
                    savedStateHandle[CONVERSATION_KEY] = nextConversation?.id
                    _uiState.value = _uiState.value.copy(
                        currentConversationId = nextConversation?.id,
                        messages = emptyList(),
                        hasOlderMessages = false
                    )
                    nextConversation?.let { loadMessages(it.id) }
                }
            } catch (error: Exception) {
                _uiState.value = _uiState.value.copy(error = userMessage(error))
            }
        }
    }

    private suspend fun loadMessages(conversationId: String) {
        if (_uiState.value.currentConversationId != conversationId) return
        _uiState.value = _uiState.value.copy(isLoadingMessages = true)
        try {
            val messages = cloudSession.getConversationMessages(
                conversationId,
                limit = MESSAGE_PAGE_SIZE
            )
                .map(::toChatMessage)
            if (_uiState.value.currentConversationId == conversationId) {
                _uiState.value = _uiState.value.copy(
                    messages = messages,
                    isLoadingMessages = false,
                    hasOlderMessages = messages.size == MESSAGE_PAGE_SIZE
                )
            }
        } catch (error: Exception) {
            if (_uiState.value.currentConversationId == conversationId) {
                _uiState.value = _uiState.value.copy(isLoadingMessages = false)
            }
            throw error
        }
    }

    fun loadOlderMessages() {
        val state = _uiState.value
        val conversationId = state.currentConversationId ?: return
        val beforeId = state.messages.firstOrNull()?.id ?: return
        if (!state.hasOlderMessages || state.isLoadingOlderMessages) return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoadingOlderMessages = true)
            try {
                val older = cloudSession.getConversationMessages(
                    conversationId,
                    limit = MESSAGE_PAGE_SIZE,
                    beforeId = beforeId
                ).map(::toChatMessage)
                if (_uiState.value.currentConversationId == conversationId) {
                    _uiState.value = _uiState.value.copy(
                        messages = older + _uiState.value.messages,
                        hasOlderMessages = older.size == MESSAGE_PAGE_SIZE,
                        isLoadingOlderMessages = false
                    )
                }
            } catch (error: Exception) {
                if (_uiState.value.currentConversationId == conversationId) {
                    _uiState.value = _uiState.value.copy(
                        isLoadingOlderMessages = false,
                        error = userMessage(error)
                    )
                }
            }
        }
    }

    private fun toChatMessage(message: RemoteConversationMessage) = ChatMessage(
        id = message.id,
        role = if (message.role == "user") ChatRole.USER else ChatRole.AGENT,
        text = message.content,
        status = message.status
    )

    private fun revealText(conversationId: String, target: String) {
        revealJob?.cancel()
        val visible = _uiState.value.streamingText
        var index = if (target.startsWith(visible)) visible.length else 0
        if (index == 0 && visible.isNotEmpty()) {
            _uiState.value = _uiState.value.copy(streamingText = "")
        }
        revealJob = viewModelScope.launch {
            val charsPerFrame = maxOf(1, target.codePointCount(0, target.length) / 120)
            while (index < target.length) {
                delay(20)
                if (_uiState.value.currentConversationId != conversationId ||
                    !_uiState.value.isSending
                ) return@launch
                index = target.offsetByCodePoints(
                    index, minOf(charsPerFrame, target.codePointCount(index, target.length))
                )
                _uiState.value = _uiState.value.copy(streamingText = target.substring(0, index))
            }
        }
    }

    fun dismissError() {
        _uiState.value = _uiState.value.copy(
            error = null,
            progressSteps = if (_uiState.value.isSending) _uiState.value.progressSteps else emptyList(),
            progressStartedAtMillis = if (_uiState.value.isSending) _uiState.value.progressStartedAtMillis else null
        )
    }

    private fun nextId(): Long = nextMessageId--

    private fun userMessage(error: Throwable): String = when (error) {
        is IllegalArgumentException -> error.message ?: "请先在个人中心登录"
        is HttpException -> when (error.code()) {
            401 -> "请先在个人中心登录"
            502 -> "智能规划上游调用失败（502），请检查服务端 LLM 配置"
            503 -> "智能规划尚未配置（503），请检查服务器 .env"
            504 -> "智能规划响应超时（504），请稍后重试"
            499 -> "请求已取消（499），请重新发送"
            else -> "请求失败，请稍后重试"
        }
        is SocketTimeoutException -> "智能规划请求超时，请稍后重试"
        is IOException -> "网络连接中断，请检查网络后重试"
        else -> error.message ?: "请求失败，请稍后重试"
    }

    private companion object {
        const val DRAFT_KEY = "smart_planning_draft"
        const val CONVERSATION_KEY = "smart_planning_conversation_id"
        const val PENDING_MESSAGE_KEY = "smart_planning_pending_message"
        const val PENDING_CONVERSATION_KEY = "smart_planning_pending_conversation_id"
        const val PENDING_CLIENT_ID_KEY = "smart_planning_pending_client_id"
        const val MESSAGE_PAGE_SIZE = 50
    }
}
