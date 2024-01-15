# Pro Tips

Voice applications have a lot of different components, each of which can be fairly complex individually.  Here are some 
tips to help you get your application built as robustly and quickly as possible.

1. *Build the LLM component independently, and test using text.*  You can think of voice as the interface to your
   application, but the underlying LLMs are all built using text.  Text is much easier to work with and a lot of the 
   development can be done using only text.  The frameworks and tools for LLMs are more mature than those for voice bots,
   and so use those tools to help you get the core conversational part of your application solid, and then layer on voice.
2. *Use a live application to build a database of example and test text.*  While the point above is true, the way people 
  talk is different from the way they write.  It's important to capture the kinds of interactions your users will really 
  have with your application, and so having test harnesses that can execute voice conversations and use transcripts of 
  those to drive you testing will be useful.
3. *Pay attention to responsiveness.*  For a voice application to work, the response time needs to be quick enough to
  feel conversational.  Pauses between user input and response that would be completely acceptable in a chat application
  will feel very unnatural in a voice application.  Use streaming whenever possible and avoid long LLM chains that take a 
  long time to produce their first token.
4. *Make sure to handle interruptions.*  In text chats, everything is naturally very orderly.  Each side can create their 
  response and hit "Enter" when they are done.  In voice applications, you can have users talking over the response.  
  This can provide a great user experience when handled well, but can be very annoying if a user is forced to listen to 
  a long LLM response that they don't care about.   
