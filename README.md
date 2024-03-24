## About StreamArchiver
Automatically opens and supervises yt-dlp processes based off a configured
list of streamers. Uses [a fork](https://github.com/bistromathica/yt-dlp) of 
yt-dlp that includes pomf.tv support. Limits concurrent streams for bandwidth.

## Installation
* Check out repo: `git clone https://github.com/bistromathica/streamarchiver.git`
* Set up Python virtual environment and activate
    * `python3 -m venv venv`
    * `source ./venv/bin/activate`
* Install packages and dependencies
    * `pip install ./streamarchiver`
    * This will automatically check out and install https://github.com/bistromathica/yt-dlp.git.
* Copy configuration and customize it. It also will look for configuration at /etc/streamarchiver.conf.
    * `cp streamarchiver/conf/streamarchiver.yaml .`
    * Customize `vods_location` and `streams` to suit your needs. 
    * The default yt-dlp options are usable out-of-the-box, but if you wish to customize, 
      [learn about its options](https://github.com/yt-dlp/yt-dlp?tab=readme-ov-file#usage-and-options). 
* Create your cookies file. By default, cookies.txt in current directory.
  You can use a browser plugin like `Get cookies.txt LOCALLY` to get your Twitch cookies. 
  A cookies file is necessary to take advantage of no ads from Twitch subs or Turbo, 
  and to have access to members-only content.
* Run `streamarchiver run`.
