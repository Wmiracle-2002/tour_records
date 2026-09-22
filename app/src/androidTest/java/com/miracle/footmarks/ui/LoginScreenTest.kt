package com.miracle.footmarks.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import com.miracle.footmarks.ui.screen.profile.CloudAccountState
import com.miracle.footmarks.ui.screen.profile.LoginContent
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class LoginScreenTest {
    @get:Rule val rule = createComposeRule()

    @Test
    fun loginPageCollectsCredentials() {
        var submitted = ""
        rule.setContent {
            LoginContent(
                state = CloudAccountState(),
                onLogin = { username, password -> submitted = "$username:$password" }
            )
        }

        rule.onNodeWithText("登录共享账号").assertIsDisplayed()
        rule.onNodeWithText("用户名").performTextClearance()
        rule.onNodeWithText("用户名").performTextInput("shared")
        rule.onNodeWithText("密码").performTextInput("password")
        rule.onNodeWithText("登录并同步").performClick()

        assertEquals("shared:password", submitted)
    }
}
