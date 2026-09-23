package com.miracle.footmarks.ui.screen.smartplanning

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.miracle.footmarks.data.remote.CloudSession
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import retrofit2.HttpException
import java.io.IOException
import java.net.SocketTimeoutException
import javax.inject.Inject

enum class ChatRole {
    USER,
    AGENT
}

data class ChatMessage(
    val id: Long,
    val role: ChatRole,
    val text: String
)

data class SmartPlanningUiState(
    val messages: List<ChatMessage> = emptyList(),
    val draft: String = "",
    val isSending: Boolean = false,
    val error: String? = null
)

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

    fun updateDraft(value: String) {
        savedStateHandle[DRAFT_KEY] = value
        _uiState.value = _uiState.value.copy(draft = value, error = null)
    }

    fun send() {
        val state = _uiState.value
        if (state.isSending) return

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
                val response = cloudSession.askAgent(message)
                savedStateHandle[DRAFT_KEY] = ""
                val current = _uiState.value
                _uiState.value = current.copy(
                    messages = current.messages + ChatMessage(
                        nextId(),
                        ChatRole.AGENT,
                        response.answer
                    ),
                    draft = "",
                    isSending = false
                )
            } catch (error: Exception) {
                savedStateHandle[DRAFT_KEY] = message
                _uiState.value = _uiState.value.copy(
                    draft = message,
                    isSending = false,
                    error = userMessage(error)
                )
            }
        }
    }

    fun dismissError() {
        _uiState.value = _uiState.value.copy(error = null)
    }

    private fun nextId(): Long = nextMessageId++

    private fun userMessage(error: Exception): String = when (error) {
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
    }
}
