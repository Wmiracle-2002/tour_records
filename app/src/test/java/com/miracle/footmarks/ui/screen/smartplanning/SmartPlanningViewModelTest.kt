package com.miracle.footmarks.ui.screen.smartplanning

import androidx.lifecycle.SavedStateHandle
import com.miracle.footmarks.data.remote.AgentChatResponse
import com.miracle.footmarks.data.remote.CloudSession
import com.miracle.footmarks.data.remote.FootmarksApi
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
    fun sendClearsDraftWhileRequestIsInFlight() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val viewModel = viewModel(FakeFootmarksApi(gate = gate))

        viewModel.updateDraft("查询我的旅行记录")
        viewModel.send()
        runCurrent()

        assertEquals("", viewModel.uiState.value.draft)
        assertTrue(viewModel.uiState.value.isSending)

        gate.complete(Unit)
        advanceUntilIdle()
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

    private fun viewModel(api: FakeFootmarksApi) = SmartPlanningViewModel(
        CloudSession(api, MemoryTokenStore(Tokens("access", "refresh"))),
        SavedStateHandle()
    )
}

private class MemoryTokenStore(
    override var tokens: Tokens? = null
) : com.miracle.footmarks.data.remote.TokenStore

private class FakeFootmarksApi(
    private val result: AgentChatResponse = AgentChatResponse("req-1", "规划完成"),
    private val failure: Exception? = null,
    private val gate: CompletableDeferred<Unit>? = null
) : FootmarksApi {
    var chatCalls = 0

    override suspend fun login(request: LoginRequest): Tokens = unsupported()

    override suspend fun chat(
        authorization: String,
        request: com.miracle.footmarks.data.remote.AgentChatRequest
    ): AgentChatResponse {
        chatCalls += 1
        gate?.await()
        failure?.let { throw it }
        return result
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
