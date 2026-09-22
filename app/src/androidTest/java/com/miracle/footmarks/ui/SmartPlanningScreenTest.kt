package com.miracle.footmarks.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import com.miracle.footmarks.ui.screen.smartplanning.ChatMessage
import com.miracle.footmarks.ui.screen.smartplanning.ChatRole
import com.miracle.footmarks.ui.screen.smartplanning.SmartPlanningContent
import com.miracle.footmarks.ui.screen.smartplanning.SmartPlanningUiState
import org.junit.Rule
import org.junit.Test

class SmartPlanningScreenTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun sendDisplaysUserAndAgentMessages() {
        setInteractiveContent()

        composeRule.onNodeWithText("输入你的旅行想法").performTextInput("北京三日游")
        composeRule.onNodeWithText("发送").performClick()

        composeRule.onNodeWithText("北京三日游").assertExists()
        composeRule.onNodeWithText("这是规划结果").assertExists()
    }

    @Test
    fun sendIsDisabledWhileRequestIsRunning() {
        setInteractiveContent(SmartPlanningUiState(draft = "北京三日游", isSending = true))

        composeRule.onNodeWithText("发送").assertIsNotEnabled()
        composeRule.onNodeWithText("正在规划…").assertIsDisplayed()
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
        composeRule.onNodeWithText("发送").performClick()
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

        composeRule.onNodeWithText("输入你的旅行想法").performTextInput("周末去苏州")
        restorationTester.emulateSavedInstanceStateRestore()

        composeRule.onNodeWithText("输入你的旅行想法")
            .assertTextContains("周末去苏州")
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
