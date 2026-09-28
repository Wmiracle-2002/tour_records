package com.miracle.footmarks.ui.screen.smartplanning

import androidx.lifecycle.SavedStateHandle
import com.miracle.footmarks.data.remote.AgentChatResponse
import com.miracle.footmarks.data.remote.CloudSession
import com.miracle.footmarks.data.remote.FootmarksApi
import com.miracle.footmarks.data.remote.RemoteConversation
import com.miracle.footmarks.data.remote.RemoteConversationMessage
import com.miracle.footmarks.data.remote.RemotePreference
import com.miracle.footmarks.data.remote.PreferenceRequest
import com.miracle.footmarks.data.remote.LoginRequest
import com.miracle.footmarks.data.remote.RecordRequest
import com.miracle.footmarks.data.remote.RefreshRequest
import com.miracle.footmarks.data.remote.RemoteRecord
import com.miracle.footmarks.data.remote.RemoteTrip
import com.miracle.footmarks.data.remote.RemoteTripSummary
import com.miracle.footmarks.data.remote.Tokens
import com.miracle.footmarks.data.remote.TripRequest
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.test.resetMain
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import java.net.SocketTimeoutException

@OptIn(ExperimentalCoroutinesApi::class)
class SmartPlanningViewModelTest {
    private val dispatcher: TestDispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun sendSuccessAddsUserAndAgentMessagesAndClearsDraft() = runTest(dispatcher) {
        val api = FakeFootmarksApi()
        val viewModel = viewModel(api)

        viewModel.updateDraft("北京三日游")
        viewModel.send()
        advanceUntilIdle()

        assertEquals("", viewModel.uiState.value.draft)
        assertFalse(viewModel.uiState.value.isSending)
        assertEquals(
            listOf(
                ChatMessage(0, ChatRole.USER, "北京三日游"),
                ChatMessage(1, ChatRole.AGENT, "规划完成")
            ),
            viewModel.uiState.value.messages
        )
        assertEquals(1, api.chatCalls)
        assertEquals(1, api.createConversationCalls)
        assertEquals("conversation-1", viewModel.uiState.value.currentConversationId)
    }

    @Test
    fun blankInputDoesNotSend() = runTest(dispatcher) {
        val api = FakeFootmarksApi()
        val viewModel = viewModel(api)

        viewModel.updateDraft("  ")
        viewModel.send()
        advanceUntilIdle()

        assertEquals(0, api.chatCalls)
        assertTrue(viewModel.uiState.value.messages.isEmpty())
    }

    @Test
    fun missingLoginShowsLoginMessageAndKeepsDraft() = runTest(dispatcher) {
        val api = FakeFootmarksApi()
        val viewModel = SmartPlanningViewModel(
            CloudSession(api, MemoryTokenStore()),
            SavedStateHandle()
        )

        viewModel.updateDraft("查看我的旅行记录")
        viewModel.send()
        advanceUntilIdle()

        assertEquals("请先在个人中心登录", viewModel.uiState.value.error)
        assertEquals("查看我的旅行记录", viewModel.uiState.value.draft)
        assertFalse(viewModel.uiState.value.isSending)
        assertEquals(1, viewModel.uiState.value.messages.size)
    }

    @Test
    fun httpErrorKeepsMessagesAndDraftForRetry() = runTest(dispatcher) {
        val api = FakeFootmarksApi(
            failure = HttpException(
                Response.error<AgentChatResponse>(
                    503,
                    "service unavailable".toResponseBody("text/plain".toMediaType())
                )
            )
        )
        val viewModel = viewModel(api)

        viewModel.updateDraft("规划北京三日游")
        viewModel.send()
        advanceUntilIdle()

        assertEquals("智能规划尚未配置（503），请检查服务器 .env", viewModel.uiState.value.error)
        assertEquals("规划北京三日游", viewModel.uiState.value.draft)
        assertEquals(1, viewModel.uiState.value.messages.size)
        assertFalse(viewModel.uiState.value.isSending)
    }

    @Test
    fun clientClosedRequestShowsRetryMessage() = runTest(dispatcher) {
        val api = FakeFootmarksApi(failure = HttpException(
            Response.error<AgentChatResponse>(
                499,
                "client closed".toResponseBody("text/plain".toMediaType())
            )
        ))
        val viewModel = viewModel(api)

        viewModel.updateDraft("规划北京三日游")
        viewModel.send()
        advanceUntilIdle()

        assertEquals("请求已取消（499），请重新发送", viewModel.uiState.value.error)
    }

    @Test
    fun socketTimeoutShowsStableRetryMessage() = runTest(dispatcher) {
        val viewModel = viewModel(FakeFootmarksApi(failure = SocketTimeoutException()))

        viewModel.updateDraft("规划北京三日游")
        viewModel.send()
        advanceUntilIdle()

        assertEquals("智能规划请求超时，请稍后重试", viewModel.uiState.value.error)
    }

    @Test
    fun retryAfterLostStreamUsesSameClientMessageId() = runTest(dispatcher) {
        val api = FakeFootmarksApi(failure = java.io.IOException("connection lost"))
        val viewModel = viewModel(api)

        viewModel.updateDraft("南京怎么玩")
        viewModel.send()
        advanceUntilIdle()
        api.failure = null
        viewModel.send()
        advanceUntilIdle()

        assertEquals(2, api.sentClientMessageIds.size)
        assertEquals(api.sentClientMessageIds.first(), api.sentClientMessageIds.last())
    }

    @Test
    fun failedRequestFollowedBySendKeepsMessageIdsUnique() = runTest(dispatcher) {
        val conversation = RemoteConversation("thread-1", "历史对话", "", "", 1)
        val api = FakeFootmarksApi(
            failure = java.io.IOException("connection lost"),
            conversations = listOf(conversation),
            messages = mapOf(conversation.id to listOf(
                RemoteConversationMessage(1, "user", "旧问题", "completed", "")
            ))
        )
        val viewModel = viewModel(api)
        advanceUntilIdle()

        viewModel.updateDraft("福州长乐有哪些风景")
        viewModel.send()
        advanceUntilIdle()
        viewModel.updateDraft("再问一个问题")
        viewModel.send()

        val ids = viewModel.uiState.value.messages.map { it.id }
        assertEquals(ids.size, ids.toSet().size)
    }

    @Test
    fun sendClearsDraftWhileRequestIsInFlight() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val viewModel = viewModel(FakeFootmarksApi(gate = gate))

        viewModel.updateDraft("查询我的旅行记录")
        viewModel.send()
        runCurrent()

        assertEquals("", viewModel.uiState.value.draft)
        assertTrue(viewModel.uiState.value.isSending)
        assertEquals("正在连接智能规划…", viewModel.uiState.value.streamingStage)

        gate.complete(Unit)
        advanceUntilIdle()
    }

    @Test
    fun streamedContentAppearsGraduallyBeforeFinalMessage() = runTest(dispatcher) {
        val answer = "南京天气晴朗，适合出游。"
        val body = "event: content\ndata: {\"request_id\":\"req-1\",\"text\":\"$answer\"}\n\n" +
            "event: completed\ndata: {\"request_id\":\"req-1\",\"answer\":\"$answer\",\"conversation_id\":\"conversation-1\"}\n\n"
        val viewModel = viewModel(FakeFootmarksApi(
            result = AgentChatResponse("req-1", answer), streamBody = body
        ))

        viewModel.updateDraft("南京天气怎么样")
        viewModel.send()
        runCurrent()
        assertTrue(viewModel.uiState.value.isSending)
        assertEquals("", viewModel.uiState.value.streamingText)

        advanceTimeBy(80)
        runCurrent()
        val partial = viewModel.uiState.value.streamingText
        assertTrue(partial.isNotEmpty())
        assertTrue(answer.startsWith(partial))
        assertTrue(partial.length < answer.length)

        advanceUntilIdle()
        assertFalse(viewModel.uiState.value.isSending)
        assertEquals(answer, viewModel.uiState.value.messages.last().text)
    }

    @Test
    fun responseDoesNotClearTextTypedWhilePreviousRequestIsInFlight() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val viewModel = viewModel(FakeFootmarksApi(gate = gate))

        viewModel.updateDraft("南京三日游")
        viewModel.send()
        runCurrent()
        viewModel.updateDraft("中秋天气怎么样")

        gate.complete(Unit)
        advanceUntilIdle()

        assertEquals("中秋天气怎么样", viewModel.uiState.value.draft)
        assertEquals(2, viewModel.uiState.value.messages.size)
    }

    @Test
    fun failureDoesNotReplaceTextTypedWhilePreviousRequestIsInFlight() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val viewModel = viewModel(
            FakeFootmarksApi(
                failure = SocketTimeoutException(),
                gate = gate
            )
        )

        viewModel.updateDraft("南京三日游")
        viewModel.send()
        runCurrent()
        viewModel.updateDraft("中秋天气怎么样")

        gate.complete(Unit)
        advanceUntilIdle()

        assertEquals("中秋天气怎么样", viewModel.uiState.value.draft)
        assertEquals("智能规划请求超时，请稍后重试", viewModel.uiState.value.error)
    }

    @Test
    fun sendingDisablesDuplicateSubmission() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val api = FakeFootmarksApi(gate = gate)
        val viewModel = viewModel(api)

        viewModel.updateDraft("北京三日游")
        viewModel.send()
        runCurrent()
        viewModel.send()

        assertTrue(viewModel.uiState.value.isSending)
        assertEquals(1, api.chatCalls)
        assertEquals(1, viewModel.uiState.value.messages.size)

        gate.complete(Unit)
        advanceUntilIdle()
        assertFalse(viewModel.uiState.value.isSending)
        assertEquals(2, viewModel.uiState.value.messages.size)
    }

    @Test
    fun draftIsRestoredFromSavedStateHandle() {
        val handle = SavedStateHandle()
        val viewModel = SmartPlanningViewModel(
            CloudSession(FakeFootmarksApi(), MemoryTokenStore(Tokens("access", "refresh"))),
            handle
        )

        viewModel.updateDraft("周末去苏州")

        val restored = SmartPlanningViewModel(
            CloudSession(FakeFootmarksApi(), MemoryTokenStore(Tokens("access", "refresh"))),
            handle
        )
        assertEquals("周末去苏州", restored.uiState.value.draft)
    }

    @Test
    fun restoresMostRecentConversationAndItsMessages() = runTest(dispatcher) {
        val conversation = RemoteConversation("conversation-1", "南京三日游", "", "", 2)
        val api = FakeFootmarksApi(
            conversations = listOf(conversation),
            messages = mapOf(
                conversation.id to listOf(
                    RemoteConversationMessage(21, "user", "南京三日游", "completed", ""),
                    RemoteConversationMessage(22, "assistant", "收到", "completed", "")
                )
            )
        )

        val viewModel = viewModel(api)
        advanceUntilIdle()

        assertEquals(conversation.id, viewModel.uiState.value.currentConversationId)
        assertEquals(
            listOf(
                ChatMessage(21, ChatRole.USER, "南京三日游"),
                ChatMessage(22, ChatRole.AGENT, "收到")
            ),
            viewModel.uiState.value.messages
        )
    }

    @Test
    fun createsNewConversationAndClearsPreviousMessages() = runTest(dispatcher) {
        val existing = RemoteConversation("conversation-1", "旧对话", "", "", 1)
        val api = FakeFootmarksApi(
            conversations = listOf(existing),
            messages = mapOf(existing.id to listOf(
                RemoteConversationMessage(1, "user", "旧问题", "completed", "")
            ))
        )
        val viewModel = viewModel(api)
        advanceUntilIdle()
        viewModel.updateDraft("保留输入")

        viewModel.createNewConversation()
        advanceUntilIdle()

        assertEquals("conversation-2", viewModel.uiState.value.currentConversationId)
        assertTrue(viewModel.uiState.value.messages.isEmpty())
        assertEquals("保留输入", viewModel.uiState.value.draft)
        assertEquals(2, viewModel.uiState.value.conversations.size)
    }

    @Test
    fun repeatedNewConversationTapsDoNotCreateMultipleEmptyThreads() = runTest(dispatcher) {
        val api = FakeFootmarksApi()
        val viewModel = viewModel(api)
        advanceUntilIdle()

        viewModel.createNewConversation()
        viewModel.createNewConversation()
        viewModel.updateDraft("南京一日游")
        viewModel.send()
        advanceUntilIdle()
        viewModel.createNewConversation()
        advanceUntilIdle()

        assertEquals(1, api.createConversationCalls)
        assertEquals(1, viewModel.uiState.value.conversations.size)
        assertEquals("conversation-1", viewModel.uiState.value.currentConversationId)
        assertEquals(0, api.chatCalls)
        assertEquals("南京一日游", viewModel.uiState.value.draft)
    }

    @Test
    fun openingAnotherConversationReplacesCurrentMessages() = runTest(dispatcher) {
        val first = RemoteConversation("thread-1", "第一段", "", "", 0)
        val second = RemoteConversation("thread-2", "第二段", "", "", 1)
        val api = FakeFootmarksApi(
            conversations = listOf(first, second),
            messages = mapOf(
                first.id to listOf(
                    RemoteConversationMessage(1, "user", "旧问题", "completed", "")
                ),
                second.id to listOf(
                    RemoteConversationMessage(2, "user", "新问题", "completed", "")
                )
            )
        )
        val viewModel = viewModel(api)
        advanceUntilIdle()

        viewModel.openConversation(second.id)
        advanceUntilIdle()

        assertEquals(second.id, viewModel.uiState.value.currentConversationId)
        assertEquals(listOf("新问题"), viewModel.uiState.value.messages.map { it.text })
    }

    @Test
    fun loadingOlderMessagesPrependsThePreviousPageInOrder() = runTest(dispatcher) {
        val conversation = RemoteConversation("thread-1", "长对话", "", "", 53)
        val messages = (0L until 53L).map { id ->
            RemoteConversationMessage(id, "user", "消息$id", "completed", "")
        }
        val viewModel = viewModel(
            FakeFootmarksApi(conversations = listOf(conversation), messages = mapOf(conversation.id to messages))
        )
        advanceUntilIdle()

        assertEquals(50, viewModel.uiState.value.messages.size)
        assertTrue(viewModel.uiState.value.hasOlderMessages)

        viewModel.loadOlderMessages()
        advanceUntilIdle()

        assertEquals(53, viewModel.uiState.value.messages.size)
        assertEquals("消息0", viewModel.uiState.value.messages.first().text)
        assertEquals("消息52", viewModel.uiState.value.messages.last().text)
        assertFalse(viewModel.uiState.value.hasOlderMessages)
    }

    @Test
    fun deletingCurrentConversationOpensAnotherThread() = runTest(dispatcher) {
        val first = RemoteConversation("thread-1", "第一段", "", "", 0)
        val second = RemoteConversation("thread-2", "第二段", "", "", 1)
        val api = FakeFootmarksApi(
            conversations = listOf(first, second),
            messages = mapOf(
                first.id to emptyList(),
                second.id to listOf(
                    RemoteConversationMessage(2, "user", "保留的对话", "completed", "")
                )
            )
        )
        val viewModel = viewModel(api)
        advanceUntilIdle()

        viewModel.deleteConversation(first.id)
        advanceUntilIdle()

        assertEquals(second.id, viewModel.uiState.value.currentConversationId)
        assertEquals(listOf(second), viewModel.uiState.value.conversations)
        assertEquals(listOf("保留的对话"), viewModel.uiState.value.messages.map { it.text })
    }

    private fun viewModel(api: FakeFootmarksApi) = SmartPlanningViewModel(
        CloudSession(api, MemoryTokenStore(Tokens("access", "refresh"))).apply {
            streamDispatcher = dispatcher
        },
        SavedStateHandle()
    )
}

private class MemoryTokenStore(
    override var tokens: Tokens? = null
) : com.miracle.footmarks.data.remote.TokenStore

private class FakeFootmarksApi(
    private val result: AgentChatResponse = AgentChatResponse("req-1", "规划完成"),
    var failure: Exception? = null,
    private val gate: CompletableDeferred<Unit>? = null,
    private val streamBody: String? = null,
    private val conversations: List<RemoteConversation> = emptyList(),
    private val messages: Map<String, List<RemoteConversationMessage>> = emptyMap()
) : FootmarksApi {
    var chatCalls = 0
    val sentClientMessageIds = mutableListOf<String?>()
    var createConversationCalls = 0
    private val storedConversations = conversations.toMutableList()
    private val storedMessages = messages.mapValues { it.value.toMutableList() }.toMutableMap()
    private val storedPreferences = mutableListOf<RemotePreference>()
    private var nextRemoteMessageId =
        storedMessages.values.flatten().maxOfOrNull { it.id + 1 } ?: 0L

    override suspend fun login(request: LoginRequest): Tokens = unsupported()

    override suspend fun streamChat(
        authorization: String,
        request: com.miracle.footmarks.data.remote.AgentChatRequest
    ): retrofit2.Response<okhttp3.ResponseBody> {
        val answer = chat(authorization, request)
        val body = "event: completed\ndata: " +
            com.google.gson.Gson().toJson(answer) + "\n\n"
        return retrofit2.Response.success(
            (streamBody ?: body).toResponseBody("text/event-stream".toMediaType())
        )
    }

    override suspend fun chat(
        authorization: String,
        request: com.miracle.footmarks.data.remote.AgentChatRequest
    ): AgentChatResponse {
        chatCalls += 1
        sentClientMessageIds += request.clientMessageId
        gate?.await()
        request.conversationId?.let { conversationId ->
            val items = storedMessages.getOrPut(conversationId) { mutableListOf() }
            items += RemoteConversationMessage(
                nextRemoteMessageId++, "user", request.message, "completed", ""
            )
        }
        failure?.let { throw it }
        request.conversationId?.let { conversationId ->
            storedMessages.getValue(conversationId) += RemoteConversationMessage(
                nextRemoteMessageId++, "assistant", result.answer, "completed", ""
            )
            storedConversations.replaceAll { conversation ->
                if (conversation.id == conversationId) conversation.copy(
                    messageCount = storedMessages.getValue(conversationId).size
                ) else conversation
            }
        }
        return result.copy(conversationId = request.conversationId)
    }

    override suspend fun createConversation(authorization: String): RemoteConversation {
        createConversationCalls += 1
        val conversation = RemoteConversation(
            "conversation-${storedConversations.size + 1}", "新对话", "", "", 0
        )
        storedConversations.add(0, conversation)
        return conversation
    }

    override suspend fun getConversations(authorization: String): List<RemoteConversation> =
        storedConversations.toList()

    override suspend fun getConversationMessages(
        authorization: String,
        conversationId: String,
        limit: Int,
        beforeId: Long?
    ): List<RemoteConversationMessage> = storedMessages[conversationId]
        .orEmpty()
        .filter { beforeId == null || it.id < beforeId }
        .takeLast(limit)

    override suspend fun deleteConversation(authorization: String, conversationId: String) {
        storedConversations.removeAll { it.id == conversationId }
        storedMessages.remove(conversationId)
    }

    override suspend fun getPreferences(authorization: String): List<RemotePreference> =
        storedPreferences.toList()

    override suspend fun upsertPreference(
        authorization: String,
        category: String,
        request: PreferenceRequest
    ): RemotePreference {
        val old = storedPreferences.firstOrNull { it.category == category }
        val value = RemotePreference(old?.id ?: (storedPreferences.size + 1L), category, request.content, "", "")
        storedPreferences.removeAll { it.category == category }
        storedPreferences.add(value)
        return value
    }

    override suspend fun deletePreference(authorization: String, category: String) {
        storedPreferences.removeAll { it.category == category }
    }

    override suspend fun getTrips(authorization: String): List<RemoteTrip> = unsupported()

    override suspend fun createTrip(
        authorization: String,
        trip: TripRequest
    ): RemoteTripSummary = unsupported()

    override suspend fun updateTrip(
        authorization: String,
        tripId: Long,
        trip: TripRequest
    ): RemoteTrip = unsupported()

    override suspend fun createRecord(
        authorization: String,
        tripId: Long,
        record: RecordRequest
    ): RemoteRecord = unsupported()

    override suspend fun updateRecord(
        authorization: String,
        recordId: Long,
        record: RecordRequest
    ): RemoteRecord = unsupported()

    override suspend fun deleteRecord(authorization: String, recordId: Long) = unsupported<Unit>()

    override suspend fun deleteTrip(authorization: String, tripId: Long) = unsupported<Unit>()

    override suspend fun uploadImage(
        authorization: String,
        recordId: Long,
        file: MultipartBody.Part
    ): com.miracle.footmarks.data.remote.RemoteImage = unsupported()

    override suspend fun getImages(
        authorization: String,
        recordId: Long
    ): List<com.miracle.footmarks.data.remote.RemoteImage> = unsupported()

    override suspend fun deleteImage(authorization: String, imageId: Long) = unsupported<Unit>()

    override suspend fun refresh(request: RefreshRequest): Tokens = unsupported()

    private fun <T> unsupported(): T = error("Not used by this test")
}
