# Edit-to-live (in content/posts folder):
#  make pub
#  make go-live

hugo-serve:
	hugo-bin/hugo_0.95.0_macOS-64bit/hugo serve

pub:
	./publish.sh

web-serve:
	cd public && http-server

go-live:
	git push origin gh-pages

