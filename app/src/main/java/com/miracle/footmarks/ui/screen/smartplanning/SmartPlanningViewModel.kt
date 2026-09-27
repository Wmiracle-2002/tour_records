package com.miracle.footmarks.ui.screen.smartplanning

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.remote.CloudSession
import com.miracle.footmarks.data.remote.RemoteConversation
import com.miracle.footmarks.data.remote.RemoteConversationMessage
import dagger.hilt.android.lifecycle.HiltViewModel
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

    private var nextMessageId = 0L

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

        savedStateHandle[DRAFT_KEY] = ""
        _uiState.value = state.copy(
            messages = state.messages + ChatMessage(nextId(), ChatRole.USER, message),
            draft = "",
            isSending = true,
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
                cloudSession.askAgent(
                    message,
                    conversationId,
                    UUID.randomUUID().toString()
                )
                if (_uiState.value.currentConversationId == conversationId) {
                    loadMessages(conversationId)
                }
                refreshConversations(selectConversation = false)
                _uiState.value = _uiState.value.copy(isSending = false)
            } catch (error: Exception) {
                val current = _uiState.value
                val restoredDraft = current.draft.ifBlank { message }
                savedStateHandle[DRAFT_KEY] = restoredDraft
                current.currentConversationId?.let { conversationId ->
                    runCatching { loadMessages(conversationId) }
                }
                _uiState.value = _uiState.value.copy(
                    draft = restoredDraft,
                    isSending = false,
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
        savedStateHandle[CONVERSATION_KEY] = conversationId
        _uiState.value = _uiState.value.copy(
            currentConversationId = conversationId,
            messages = emptyList(),
            hasOlderMessages = false,
            isLoadingMessages = false,
            isLoadingOlderMessages = false,
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

    fun dismissError() {
        _uiState.value = _uiState.value.copy(error = null)
    }

    private fun nextId(): Long = nextMessageId++

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
        const val MESSAGE_PAGE_SIZE = 50
    }
}
