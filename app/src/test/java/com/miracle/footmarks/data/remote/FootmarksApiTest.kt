package com.miracle.footmarks.data.remote

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class FootmarksApiTest {
    @Test
    fun readsCreatesUpdatesAndDeletesTravelPreferences() = runBlocking {
        MockWebServer().use { server ->
            val preference = """{"id":4,"category":"food_restriction","content":"不吃辣","created_at":"now","updated_at":"now"}"""
            server.enqueue(MockResponse().setBody("[$preference]")
                .addHeader("Content-Type", "application/json"))
            server.enqueue(MockResponse().setBody(preference)
                .addHeader("Content-Type", "application/json"))
            server.enqueue(MockResponse().setResponseCode(204))
            server.start()
            val api = FootmarksApi.create(server.url("/").toString())

            assertEquals("不吃辣", api.getPreferences("Bearer token").single().content)
            api.upsertPreference(
                "Bearer token", "food_restriction", PreferenceRequest("不吃辣")
            )
            api.deletePreference("Bearer token", "food_restriction")

            assertEquals("/api/v1/agent/preferences", server.takeRequest().path)
            val update = server.takeRequest()
            assertEquals("PUT", update.method)
            assertEquals("/api/v1/agent/preferences/food_restriction", update.path)
            assertEquals("{\"content\":\"不吃辣\"}", update.body.readUtf8())
            val delete = server.takeRequest()
            assertEquals("DELETE", delete.method)
            assertEquals("/api/v1/agent/preferences/food_restriction", delete.path)
            assertEquals("Bearer token", delete.getHeader("Authorization"))
        }
    }

    @Test
    fun conversationAndChatEndpointsMatchServerContract() = runBlocking {
        MockWebServer().use { server ->
            val conversation = """{"id":"thread-1","title":"南京三日游","created_at":"now","updated_at":"now","message_count":2}"""
            server.enqueue(MockResponse().setResponseCode(201).setBody(conversation)
                .addHeader("Content-Type", "application/json"))
            server.enqueue(MockResponse().setBody("[$conversation]")
                .addHeader("Content-Type", "application/json"))
            server.enqueue(MockResponse().setBody(
                """[{"id":1,"role":"user","content":"南京三日游","status":"completed","created_at":"now"}]"""
            ).addHeader("Content-Type", "application/json"))
            server.enqueue(MockResponse().setResponseCode(204))
            server.enqueue(MockResponse().setBody(
                """{"request_id":"req-1","answer":"规划完成","conversation_id":"thread-1"}"""
            ).addHeader("Content-Type", "application/json"))
            server.start()
            val api = FootmarksApi.create(server.url("/").toString())

            assertEquals("thread-1", api.createConversation("Bearer token").id)
            assertEquals("thread-1", api.getConversations("Bearer token").single().id)
            assertEquals(
                "南京三日游",
                api.getConversationMessages("Bearer token", "thread-1", 50, null)
                    .single().content
            )
            api.deleteConversation("Bearer token", "thread-1")
            val response = api.chat(
                "Bearer token",
                AgentChatRequest("南京三日游", "thread-1", "client-1")
            )

            assertEquals("/api/v1/agent/conversations", server.takeRequest().path)
            assertEquals("/api/v1/agent/conversations", server.takeRequest().path)
            assertEquals(
                "/api/v1/agent/conversations/thread-1/messages?limit=50",
                server.takeRequest().path
            )
            assertEquals("DELETE", server.takeRequest().method)
            val chatRequest = server.takeRequest()
            assertEquals("/api/v1/agent/chat", chatRequest.path)
            assertEquals(
                "{\"message\":\"南京三日游\",\"conversation_id\":\"thread-1\",\"client_message_id\":\"client-1\"}",
                chatRequest.body.readUtf8()
            )
            assertEquals("thread-1", response.conversationId)
        }
    }

    @Test
    fun defaultClientMatchesAgentRequestBudget() {
        val client = FootmarksApi.defaultClient()

        assertEquals(150_000, client.readTimeoutMillis)
        assertEquals(150_000, client.callTimeoutMillis)
    }

    @Test
    fun loginAndReadTripsMatchServerContract() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(
                MockResponse().setBody("""{"access_token":"access","refresh_token":"refresh","token_type":"bearer"}""")
                    .addHeader("Content-Type", "application/json")
            )
            server.enqueue(
                MockResponse().setBody(
                    """[{"id":8,"province_code":"110000","city_code":"110100","city_name":"北京市","start_date":"2026-09-01","end_date":"2026-09-03","created_at":"2026-09-01T10:00:00","records":[{"id":12,"trip_id":8,"type":"FOOD","name":"烤鸭","date":"2026-09-02","rating":null,"cost":"88.50","notes":null,"created_at":"2026-09-02T10:00:00"}]}]"""
                ).addHeader("Content-Type", "application/json")
            )
            server.start()
            val api = FootmarksApi.create(server.url("/").toString())

            val tokens = api.login(LoginRequest("shared", "password"))
            val trips = api.getTrips("Bearer ${tokens.accessToken}")

            assertEquals("POST", server.takeRequest().method)
            val request = server.takeRequest()
            assertEquals("/api/v1/trips", request.path)
            assertEquals("Bearer access", request.getHeader("Authorization"))
            assertEquals("110100", trips.single().cityCode)
            assertEquals("88.50", trips.single().records.single().cost)
        }
    }

    @Test
    fun writesUseAuthenticatedTripAndRecordEndpoints() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(201).setBody("""{"id":8,"province_code":"110000","city_code":"110100","city_name":"北京市","start_date":"2026-09-01","end_date":"2026-09-03","created_at":"2026-09-01T10:00:00"}""").addHeader("Content-Type", "application/json"))
            server.enqueue(MockResponse().setResponseCode(201).setBody("""{"id":12,"trip_id":8,"type":"FOOD","name":"烤鸭","date":"2026-09-02","rating":null,"cost":"88.50","notes":null,"created_at":"2026-09-02T10:00:00"}""").addHeader("Content-Type", "application/json"))
            server.enqueue(MockResponse().setResponseCode(204))
            server.start()
            val api = FootmarksApi.create(server.url("/").toString())

            val trip = api.createTrip("Bearer token", TripRequest("110000", "110100", "北京市", "2026-09-01", "2026-09-03"))
            val record = api.createRecord("Bearer token", trip.id, RecordRequest("FOOD", "烤鸭", "2026-09-02", null, "88.50", null))
            api.deleteRecord("Bearer token", record.id)

            assertEquals("/api/v1/trips", server.takeRequest().path)
            val create = server.takeRequest()
            assertEquals("/api/v1/trips/8/records", create.path)
            assertEquals("Bearer token", create.getHeader("Authorization"))
            assertEquals("/api/v1/records/12", server.takeRequest().path)
        }
    }

    @Test
    fun sessionRefreshesExpiredAccessBeforeReadingTrips() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("""{"access_token":"old","refresh_token":"refresh","token_type":"bearer"}""").addHeader("Content-Type", "application/json"))
            server.enqueue(MockResponse().setResponseCode(401))
            server.enqueue(MockResponse().setBody("""{"access_token":"new","refresh_token":"new-refresh","token_type":"bearer"}""").addHeader("Content-Type", "application/json"))
            server.enqueue(MockResponse().setBody("[]").addHeader("Content-Type", "application/json"))
            server.start()
            val session = CloudSession(FootmarksApi.create(server.url("/").toString()), MemoryTokenStore())

            session.login("shared", "password")
            assertEquals(emptyList<RemoteTrip>(), session.getTrips())
            server.takeRequest()
            assertEquals("Bearer old", server.takeRequest().getHeader("Authorization"))
            assertEquals("/api/v1/auth/refresh", server.takeRequest().path)
            assertEquals("Bearer new", server.takeRequest().getHeader("Authorization"))
        }
    }

    @Test
    fun movingSingleDayRecordSendsTripAndRecordInOneRequest() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("""{"id":12,"trip_id":8,"type":"FOOD","name":"烤鸭","date":"2026-09-05","rating":null,"cost":null,"notes":null}""").addHeader("Content-Type", "application/json"))
            server.start()
            val api = FootmarksApi.create(server.url("/").toString())
            api.updateRecord(
                "Bearer access", 12,
                RecordRequest("FOOD", "烤鸭", "2026-09-05", null, null, null,
                    TripRequest("110000", "110100", "北京市", "2026-09-05", "2026-09-05"))
            )
            val request = server.takeRequest()
            assertEquals("PATCH", request.method)
            assertEquals("/api/v1/records/12", request.path)
            org.junit.Assert.assertTrue(request.body.readUtf8().contains("\"start_date\":\"2026-09-05\""))
        }
    }

    @Test
    fun agentChatUsesAuthenticatedEndpointAndParsesResponse() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(
                MockResponse()
                    .setBody("""{"request_id":"req-1","answer":"行程结果"}""")
                    .addHeader("Content-Type", "application/json")
            )
            server.start()
            val api = FootmarksApi.create(server.url("/").toString())

            val response = api.chat(
                "Bearer access",
                AgentChatRequest("北京三日游")
            )

            val request = server.takeRequest()
            assertEquals("POST", request.method)
            assertEquals("/api/v1/agent/chat", request.path)
            assertEquals("Bearer access", request.getHeader("Authorization"))
            assertEquals("{\"message\":\"北京三日游\"}", request.body.readUtf8())
            assertEquals("req-1", response.requestId)
            assertEquals("行程结果", response.answer)
        }
    }

    @Test
    fun agentChatRefreshesExpiredAccessTokenOnce() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(401))
            server.enqueue(
                MockResponse()
                    .setBody("""{"access_token":"new-access","refresh_token":"new-refresh","token_type":"bearer"}""")
                    .addHeader("Content-Type", "application/json")
            )
            server.enqueue(
                MockResponse()
                    .setBody("""{"request_id":"req-2","answer":"规划完成"}""")
                    .addHeader("Content-Type", "application/json")
            )
            server.start()
            val store = MemoryTokenStore().apply {
                tokens = Tokens("old-access", "refresh")
            }
            val session = CloudSession(FootmarksApi.create(server.url("/").toString()), store)

            val response = session.askAgent("北京三日游")

            val expiredRequest = server.takeRequest()
            val refreshRequest = server.takeRequest()
            val retriedRequest = server.takeRequest()
            assertEquals("/api/v1/agent/chat", expiredRequest.path)
            assertEquals("Bearer old-access", expiredRequest.getHeader("Authorization"))
            assertEquals("/api/v1/auth/refresh", refreshRequest.path)
            assertEquals("Bearer new-access", retriedRequest.getHeader("Authorization"))
            assertEquals("req-2", response.requestId)
            assertEquals("new-refresh", store.tokens?.refreshToken)
        }
    }

    @Test
    fun agentStreamDeliversStagesAndContentBeforeCompletion() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(
                MockResponse().addHeader("Content-Type", "text/event-stream")
                    .setBody(
                        "event: started\ndata: {\"request_id\":\"req-3\"}\n\n" +
                            "event: stage\ndata: {\"request_id\":\"req-3\",\"message\":\"正在规划行程\"}\n\n" +
                            "event: preview\ndata: {\"request_id\":\"req-3\",\"text\":\"第1天：中山陵\"}\n\n" +
                            "event: content\ndata: {\"request_id\":\"req-3\",\"text\":\"第一天\\n\"}\n\n" +
                            "event: completed\ndata: {\"request_id\":\"req-3\",\"answer\":\"第一天\\n\",\"conversation_id\":\"chat-1\"}\n\n"
                    )
            )
            server.start()
            val store = MemoryTokenStore().apply { tokens = Tokens("access", "refresh") }
            val session = CloudSession(FootmarksApi.create(server.url("/").toString()), store)
            val received = mutableListOf<AgentStreamEvent>()

            val answer = session.streamAgent("南京一日游", "chat-1", "message-1") { received += it }

            assertEquals("/api/v1/agent/chat/stream", server.takeRequest().path)
            assertEquals(listOf("started", "stage", "preview", "content", "completed"), received.map { it.name })
            assertEquals("正在规划行程", received[1].message)
            assertEquals("第1天：中山陵", received[2].text)
            assertEquals("第一天\n", received[3].text)
            assertEquals("第一天\n", answer.answer)
        }
    }

    @Test
    fun agentStreamShowsStageWhileHttpResponseIsStillOpen() = runBlocking {
        MockWebServer().use { server ->
            val prefix = "event: started\ndata: {\"request_id\":\"req-5\"}\n\n" +
                "event: stage\ndata: {\"request_id\":\"req-5\",\"message\":\"正在查找地点\"}\n\n"
            val suffix = "event: completed\ndata: {\"request_id\":\"req-5\",\"answer\":\"找到地点\",\"conversation_id\":\"chat-1\"}\n\n"
            server.enqueue(
                MockResponse().addHeader("Content-Type", "text/event-stream")
                    .setBody(prefix + suffix)
                    .throttleBody(prefix.toByteArray().size.toLong(), 2, java.util.concurrent.TimeUnit.SECONDS)
            )
            server.start()
            val store = MemoryTokenStore().apply { tokens = Tokens("access", "refresh") }
            val session = CloudSession(FootmarksApi.create(server.url("/").toString()), store)
            val stageArrived = CompletableDeferred<Unit>()
            val request = async {
                session.streamAgent("福州长乐风景推荐", "chat-1", "message-1") {
                    if (it.name == "stage") stageArrived.complete(Unit)
                }
            }

            withTimeout(1500) { stageArrived.await() }
            assertFalse(request.isCompleted)
            assertEquals("找到地点", request.await().answer)
        }
    }

    @Test
    fun agentStreamRejectsTruncatedAnswer() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(
                MockResponse().addHeader("Content-Type", "text/event-stream")
                    .setBody("event: content\ndata: {\"request_id\":\"req-4\",\"text\":\"半截回答\"}\n\n")
            )
            server.start()
            val store = MemoryTokenStore().apply { tokens = Tokens("access", "refresh") }
            val session = CloudSession(FootmarksApi.create(server.url("/").toString()), store)

            try {
                session.streamAgent("测试", "chat-1", "message-1") { }
                org.junit.Assert.fail("Missing completed event should fail")
            } catch (error: java.io.IOException) {
                org.junit.Assert.assertTrue(error.message?.contains("中断") == true)
            }
        }
    }

    private class MemoryTokenStore : TokenStore {
        override var tokens: Tokens? = null
    }
}
