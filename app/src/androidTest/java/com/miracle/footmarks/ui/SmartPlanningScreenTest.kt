package com.miracle.footmarks.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import com.miracle.footmarks.ui.screen.smartplanning.ChatMessage
import com.miracle.footmarks.ui.screen.smartplanning.ChatRole
import com.miracle.footmarks.ui.screen.smartplanning.SmartPlanningContent
import com.miracle.footmarks.ui.screen.smartplanning.SmartPlanningUiState
import com.miracle.footmarks.data.remote.RemoteConversation
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.assertTrue

class SmartPlanningScreenTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun sendDisplaysUserAndAgentMessages() {
        setInteractiveContent()

        composeRule.onNodeWithText("说说你想去哪里").performTextInput("北京三日游")
        composeRule.onNodeWithContentDescription("发送").performClick()

        composeRule.onNodeWithText("北京三日游").assertExists()
        composeRule.onNodeWithText("这是规划结果").assertExists()
    }

    @Test
    fun sendIsDisabledWhileRequestIsRunning() {
        setInteractiveContent(SmartPlanningUiState(draft = "北京三日游", isSending = true))

        composeRule.onNodeWithContentDescription("发送").assertIsNotEnabled()
        composeRule.onNodeWithText("正在整理你的旅行灵感…").assertIsDisplayed()
    }

    @Test
    fun errorKeepsExistingMessagesAndAllowsRetry() {
        composeRule.setContent {
            var state by remember {
                mutableStateOf(
                    SmartPlanningUiState(
                        messages = listOf(ChatMessage(0, ChatRole.AGENT, "历史回答")),
                        draft = "再次请求",
                        error = "智能规划响应超时（504），请稍后重试"
                    )
                )
            }
            SmartPlanningContent(
                uiState = state,
                onDraftChange = { state = state.copy(draft = it) },
                onSend = {
                    state = state.copy(
                        messages = state.messages + ChatMessage(1, ChatRole.AGENT, "重试成功"),
                        draft = "",
                        error = null
                    )
                },
                onDismissError = { state = state.copy(error = null) }
            )
        }

        composeRule.onNodeWithText("历史回答").assertIsDisplayed()
        composeRule.onNodeWithText("智能规划响应超时（504），请稍后重试").assertIsDisplayed()
        composeRule.onNodeWithContentDescription("发送").performClick()
        composeRule.onNodeWithText("重试成功").assertIsDisplayed()
    }

    @Test
    fun draftSurvivesSavedStateRestoration() {
        val restorationTester = StateRestorationTester(composeRule)
        restorationTester.setContent {
            var draft by rememberSaveable { mutableStateOf("") }
            SmartPlanningContent(
                uiState = SmartPlanningUiState(draft = draft),
                onDraftChange = { draft = it },
                onSend = {},
                onDismissError = {}
            )
        }

        composeRule.onNodeWithText("说说你想去哪里").performTextInput("周末去苏州")
        restorationTester.emulateSavedInstanceStateRestore()

        composeRule.onNodeWithText("周末去苏州").assertIsDisplayed()
    }

    @Test
    fun streamingStageChangesToPartialAnswer() {
        var state by mutableStateOf(
            SmartPlanningUiState(isSending = true, streamingStage = "正在规划行程")
        )
        composeRule.setContent {
            SmartPlanningContent(state, onDraftChange = {}, onSend = {}, onDismissError = {})
        }

        composeRule.onNodeWithText("正在规划行程").assertIsDisplayed()
        composeRule.runOnUiThread {
            state = state.copy(streamingText = "第1天：中山陵\n")
        }
        composeRule.onNodeWithText("第1天：中山陵\n").assertIsDisplayed()
    }

    @Test
    fun streamingStageStaysVisibleAfterOlderMessages() {
        val messages = (1..15).map { index ->
            ChatMessage(
                index.toLong(), ChatRole.USER,
                if (index == 15) "历史问题 $index\n".repeat(60) else "历史问题 $index"
            )
        }
        var state by mutableStateOf(SmartPlanningUiState(
            messages = messages,
            hasOlderMessages = true,
            isSending = true,
            streamingStage = "正在查找地点"
        ))
        composeRule.setContent {
            SmartPlanningContent(
                state,
                onDraftChange = {}, onSend = {}, onDismissError = {}
            )
        }

        composeRule.onNodeWithText("正在查找地点").assertIsDisplayed()
        composeRule.runOnUiThread {
            state = state.copy(streamingText = "第1天：中山陵")
        }
        composeRule.onNodeWithText("第1天：中山陵").assertIsDisplayed()
    }

    @Test
    fun noConversationShowsTheNewConversationSurface() {
        setInteractiveContent()

        composeRule.onNodeWithText("开始一段新对话").assertIsDisplayed()
        composeRule.onNodeWithText("当前是新对话").assertIsNotEnabled()
        composeRule.onNodeWithText("说说你想去哪里").assertIsDisplayed()
    }

    @Test
    fun newEmptyConversationShowsTheSameSurfaceAndCannotBeCreatedTwice() {
        val existing = RemoteConversation("thread-old", "旧对话", "", "", 1)
        val conversation = RemoteConversation("thread-1", "新对话", "", "", 0)
        composeRule.setContent {
            var state by remember {
                mutableStateOf(SmartPlanningUiState(
                    conversations = listOf(existing),
                    currentConversationId = existing.id,
                    messages = listOf(ChatMessage(1, ChatRole.USER, "旧问题"))
                ))
            }
            SmartPlanningContent(
                uiState = state,
                onDraftChange = {},
                onSend = {},
                onDismissError = {},
                onCreateConversation = {
                    state = state.copy(
                        conversations = listOf(conversation, existing),
                        currentConversationId = conversation.id,
                        messages = emptyList()
                    )
                }
            )
        }

        composeRule.onNodeWithText("开始一段新对话").assertDoesNotExist()
        composeRule.onNodeWithText("新对话").performClick()
        composeRule.onNodeWithText("开始一段新对话").assertIsDisplayed()
        composeRule.onNodeWithText("当前是新对话").assertIsNotEnabled()
    }

    @Test
    fun creatingConversationDisablesNewAndSendActions() {
        setInteractiveContent(
            SmartPlanningUiState(draft = "南京一日游", isCreatingConversation = true)
        )

        composeRule.onNodeWithText("创建中…").assertIsNotEnabled()
        composeRule.onNodeWithContentDescription("发送").assertIsNotEnabled()
    }

    @Test
    fun olderMessagesCanBeRequestedFromTheConversation() {
        var loadRequested = false
        composeRule.setContent {
            var hasOlderMessages by remember { mutableStateOf(true) }
            SmartPlanningContent(
                uiState = SmartPlanningUiState(hasOlderMessages = hasOlderMessages),
                onDraftChange = {},
                onSend = {},
                onDismissError = {},
                onLoadOlderMessages = {
                    loadRequested = true
                    hasOlderMessages = false
                }
            )
        }

        composeRule.onNodeWithText("加载更早消息").assertIsDisplayed().performClick()
        composeRule.runOnIdle { assertTrue(loadRequested) }
    }

    @Test
    fun conversationSheetListsThreadsAndConfirmsDeletion() {
        val conversation = RemoteConversation("thread-1", "南京三日游", "", "", 4)
        composeRule.setContent {
            SmartPlanningContent(
                uiState = SmartPlanningUiState(conversations = listOf(conversation)),
                onDraftChange = {},
                onSend = {},
                onDismissError = {}
            )
        }

        composeRule.onNodeWithText("对话列表").performClick()
        composeRule.onNodeWithText("南京三日游").assertIsDisplayed()
        composeRule.onNodeWithText("4 条消息").assertIsDisplayed()
        composeRule.onAllNodesWithText("删除")[0].performClick()
        composeRule.onNodeWithText("删除对话？").assertIsDisplayed()
        composeRule.onAllNodesWithText("删除").get(1).performClick()
    }

    private fun setInteractiveContent(initial: SmartPlanningUiState = SmartPlanningUiState()) {
        composeRule.setContent {
            var state by remember { mutableStateOf(initial) }
            SmartPlanningContent(
                uiState = state,
                onDraftChange = { state = state.copy(draft = it) },
                onSend = {
                    val message = state.draft.trim()
                    val firstId = state.messages.size.toLong()
                    state = state.copy(
                        messages = state.messages + listOf(
                            ChatMessage(firstId, ChatRole.USER, message),
                            ChatMessage(firstId + 1, ChatRole.AGENT, "这是规划结果")
                        ),
                        draft = "",
                        isSending = false
                    )
                },
                onDismissError = { state = state.copy(error = null) }
            )
        }
    }
}
